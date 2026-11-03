"""CPU file validation for the supplied model-preparation workflow."""

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3

from artifact_loader import copy_verified, safe_path
from model_intake import collect
from pipeline_artifacts import put_json, read_pinned_json, runtime_findings, s3_location, validate_candidate
from scan_gate import check_scans, read_events


def checked_file(path, expected_hash):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError("Pinned model policy hash mismatch")
    return json.loads(raw)


def download(s3, candidate, root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError("Use an empty model directory")
    for item in candidate["files"]:
        target = root / safe_path(item["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        body = s3.get_object(Bucket=candidate["bucket"], Key=item["key"], VersionId=item["version_id"])["Body"]
        copy_verified(body, target, item["sha256"], item["bytes"])


def validate_formats(root, candidate):
    from safetensors import safe_open
    from quarantine_intake import METADATA
    names = {item["path"] for item in candidate["files"]}
    for item in candidate["files"]:
        name = item["path"]
        if name.endswith(".safetensors"):
            with safe_open(str(Path(root) / name), framework="numpy") as weights:
                if not list(weights.keys()):
                    raise ValueError("Empty safetensors shard")
        elif name not in METADATA:
            raise ValueError("Unexpected model file type")
    for name in ("config.json", "tokenizer_config.json"):
        config = json.loads((Path(root) / name).read_text())
        if config.get("auto_map"):
            raise ValueError("Custom model code is not allowed")
    index = Path(root) / "model.safetensors.index.json"
    if index.exists():
        mapped = set(json.loads(index.read_text())["weight_map"].values())
        actual = {name for name in names if name.endswith(".safetensors")}
        if mapped != actual:
            raise ValueError("Weight index does not match the verified shards")


def common(args, session):
    s3 = session.client("s3")
    policy = checked_file(args.policy, args.policy_sha256)
    candidate = read_pinned_json(s3, args.manifest_uri, args.manifest_version, args.manifest_sha256)
    validate_candidate(candidate, args.release_id, args.quarantine_bucket)
    for key in ("source_repository", "source_revision", "license_label"):
        if candidate[key] != policy[key]:
            raise ValueError("Candidate differs from the reviewed policy: " + key)
    if "@sha256:" not in args.runtime_image:
        raise ValueError("Runtime image must be pinned")
    subject = {"manifest_sha256": args.manifest_sha256,
               "runtime_digest": args.runtime_image.rsplit("@", 1)[1],
               "policy_sha256": args.policy_sha256}
    report = {
        "schema": 1, "release_id": args.release_id, "subject": subject,
        "runtime_image": args.runtime_image,
        "candidate": {"uri": args.manifest_uri, "version": args.manifest_version, "sha256": args.manifest_sha256},
        "valid_until": (datetime.now(timezone.utc) + timedelta(hours=policy["evidence_valid_hours"])).isoformat(),
        "checks": {}, "passed": False,
    }
    return s3, policy, candidate, report


def save(args, s3, report, name):
    reference = put_json(s3, args.evidence_bucket, f"pipeline/{args.execution_id}/{name}.json", report)
    output = Path("/opt/ml/processing/output")
    output.mkdir(parents=True, exist_ok=True)
    value = {"passed": report["passed"], "evidence": reference,
             "release_id": report["release_id"], "subject": report["subject"]}
    (output / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
    print(json.dumps(value), flush=True)


def validate(args, session):
    s3, policy, candidate, report = common(args, session)
    try:
        # Recheck immutable publisher metadata, rather than trust the uploader's labels.
        publisher = collect(candidate["source_repository"], candidate["source_revision"])
        if publisher["license_label"] != policy["license_label"]:
            raise ValueError("Publisher license differs from reviewed policy")
        expected_weights = {item["path"]: item for item in publisher["weights"]}
        actual_weights = {item["path"]: item for item in candidate["files"] if item["path"].endswith(".safetensors")}
        if expected_weights.keys() != actual_weights.keys():
            raise ValueError("Candidate weight inventory differs from the publisher")
        for name, original in expected_weights.items():
            if (actual_weights[name]["sha256"] != original["reported_sha256"]
                    or actual_weights[name]["bytes"] != original["reported_bytes"]):
                raise ValueError("Candidate weight differs from the publisher")
        for item in candidate["files"]:
            original_hash = publisher["downloaded_metadata_sha256"].get(item["path"])
            if original_hash and original_hash != item["sha256"]:
                raise ValueError("Candidate metadata differs from the publisher")
        scan = read_pinned_json(s3, args.runtime_scan_uri, args.runtime_scan_version,
                                args.runtime_scan_sha256, limit=32 * 1024 * 1024)
        findings = runtime_findings(scan, args.runtime_image)
        if args.runtime_exception_uri:
            from runtime_exception import apply_exception
            if s3_location(args.runtime_exception_uri)[0] != args.evidence_bucket:
                raise ValueError("Runtime exception is outside the trusted evidence bucket")
            exception = read_pinned_json(s3, args.runtime_exception_uri, args.runtime_exception_version,
                                         args.runtime_exception_sha256)
            findings, accepted = apply_exception(findings, exception, args.runtime_image)
            report["runtime_exception"] = {"uri": args.runtime_exception_uri,
                "version": args.runtime_exception_version, "sha256": args.runtime_exception_sha256,
                "accepted_findings": len(accepted), "valid_until": exception["valid_until"]}
            if datetime.fromisoformat(exception["valid_until"].replace("Z", "+00:00")) < datetime.fromisoformat(report["valid_until"]):
                report["valid_until"] = exception["valid_until"]
        if findings:
            raise ValueError(f"Runtime scan has {len(findings)} HIGH/CRITICAL findings")
        report["runtime_scan"] = {"uri": args.runtime_scan_uri, "version": args.runtime_scan_version,
                                  "sha256": args.runtime_scan_sha256}
        report["checks"]["runtime_scan"] = "PASS"
        account = session.client("sts").get_caller_identity()["Account"]
        events = read_events(session.client("logs"), args.scan_log_group)
        report["malware"] = check_scans(candidate, events, account, args.malware_plan_arn)
        report["checks"]["malware"] = "PASS"
        download(s3, candidate, args.model_directory)
        report["checks"]["file_integrity"] = "PASS"
        validate_formats(args.model_directory, candidate)
        report["checks"].update(file_format="PASS", provenance="PASS", license="PASS")
        report["passed"] = True
    except Exception as error:
        report["error"] = type(error).__name__ + ": " + str(error)[:400]
        save(args, s3, report, "validation")
        raise
    save(args, s3, report, "validation")



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["validate"])
    for name in ("release-id", "manifest-uri", "manifest-version", "manifest-sha256", "quarantine-bucket",
                 "evidence-bucket", "execution-id", "runtime-image", "policy-sha256"):
        parser.add_argument("--" + name, required=True)
    for name in ("runtime-scan-uri", "runtime-scan-version", "runtime-scan-sha256", "scan-log-group",
                 "malware-plan-arn",
                 "runtime-exception-uri", "runtime-exception-version", "runtime-exception-sha256"):
        parser.add_argument("--" + name)
    parser.add_argument("--policy", default="/opt/astra/model-policy.json")
    parser.add_argument("--model-directory", default="/opt/ml/processing/model")
    args = parser.parse_args()
    session = boto3.Session(region_name="us-east-1")
    validate(args, session)


if __name__ == "__main__":
    main()
