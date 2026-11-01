"""SageMaker Processing entry point for validation and real GPU evaluation."""

import argparse
import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3

from artifact_loader import copy_verified, safe_path
from evaluate_model import evaluate
from managed_mlflow import Tracking
from model_intake import collect
from pipeline_artifacts import put_json, read_pinned_json, runtime_findings, s3_location, validate_candidate
from scan_gate import check_scans, read_events


def checked_file(path, expected_hash):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError("Pinned evaluation file hash mismatch")
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
    dataset = checked_file(args.dataset, args.evalset_sha256)
    candidate = read_pinned_json(s3, args.manifest_uri, args.manifest_version, args.manifest_sha256)
    validate_candidate(candidate, args.release_id, args.quarantine_bucket)
    for key in ("source_repository", "source_revision", "license_label"):
        if candidate[key] != policy[key]:
            raise ValueError("Candidate differs from the reviewed policy: " + key)
    if "@sha256:" not in args.runtime_image:
        raise ValueError("Runtime image must be pinned")
    subject = {"manifest_sha256": args.manifest_sha256,
               "runtime_digest": args.runtime_image.rsplit("@", 1)[1],
               "policy_sha256": args.policy_sha256, "evalset_sha256": args.evalset_sha256}
    report = {
        "schema": 1, "release_id": args.release_id, "subject": subject,
        "runtime_image": args.runtime_image,
        "candidate": {"uri": args.manifest_uri, "version": args.manifest_version, "sha256": args.manifest_sha256},
        "valid_until": (datetime.now(timezone.utc) + timedelta(hours=policy["evidence_valid_hours"])).isoformat(),
        "checks": {}, "passed": False,
    }
    return s3, policy, dataset, candidate, report


def save(args, s3, report, name):
    reference = put_json(s3, args.evidence_bucket, f"pipeline/{args.execution_id}/{name}.json", report)
    output = Path("/opt/ml/processing/output")
    output.mkdir(parents=True, exist_ok=True)
    value = {"passed": report["passed"], "evidence": reference,
             "release_id": report["release_id"], "subject": report["subject"],
             "mlflow_run_id": report.get("mlflow_run_id", ""),
             "model_source": report.get("model_source", "")}
    (output / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
    print(json.dumps(value), flush=True)


def validate(args, session):
    s3, policy, dataset, candidate, report = common(args, session)
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


def evaluate_gpu(args, session):
    s3, policy, dataset, candidate, report = common(args, session)
    bucket, key = s3_location(args.validation_uri)
    if bucket != args.evidence_bucket or key != f"pipeline/{args.execution_id}/validation.json":
        raise ValueError("Validation report is outside this execution")
    response = s3.get_object(Bucket=bucket, Key=key)
    with response["Body"] as body:
        raw = body.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024 or not response.get("VersionId") or response["VersionId"] == "null":
        raise ValueError("Validation report must be bounded and versioned")
    validation = json.loads(raw)
    if (not validation.get("passed") or validation["subject"] != report["subject"]
            or validation["release_id"] != args.release_id):
        raise ValueError("Validation did not pass for these exact inputs")
    expires = datetime.fromisoformat(validation["valid_until"].replace("Z", "+00:00"))
    if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
        raise ValueError("Validation evidence has expired")
    report["valid_until"] = validation["valid_until"]
    report["checks"].update(validation["checks"])
    report["validation"] = {"uri": args.validation_uri, "version": response["VersionId"],
                            "sha256": hashlib.sha256(raw).hexdigest()}
    download(s3, candidate, args.model_directory)
    command = ["vllm", "serve", args.model_directory, "--host", "127.0.0.1", "--port", "8000",
               "--served-model-name", "astra", "--max-model-len", str(policy["max_model_len"]),
               "--max-num-seqs", str(policy["max_num_seqs"]),
               "--gpu-memory-utilization", str(policy["gpu_memory_utilization"]),
               "--load-format", "safetensors", "--language-model-only", "--enable-auto-tool-choice",
               "--tool-call-parser", "qwen3_coder", "--reasoning-parser", "qwen3",
               "--default-chat-template-kwargs", '{"enable_thinking": false}']
    env = dict(os.environ, HF_HUB_OFFLINE="1", VLLM_NO_USAGE_STATS="1", DO_NOT_TRACK="1")
    # The evaluation service is loopback-only and is stopped in finally.
    process = subprocess.Popen(command, env=env)
    try:
        deadline = time.monotonic() + 1200
        while True:
            if process.poll() is not None:
                raise RuntimeError("vLLM stopped during initialization")
            try:
                with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5) as health:
                    if health.status == 200:
                        break
            except (OSError, urllib.error.URLError):
                pass
            if time.monotonic() > deadline:
                raise TimeoutError("vLLM did not become healthy within 20 minutes")
            time.sleep(5)
        report["evaluation"] = evaluate("http://127.0.0.1:8000/v1", dataset, policy)
        report["checks"].update(report["evaluation"]["checks"])
        report["passed"] = report["evaluation"]["passed"]
        report["runtime_command"] = command
        report["model_source"] = f"s3://{candidate['bucket']}/" + candidate["files"][0]["key"].rsplit("/", 1)[0] + "/"
        report["mlflow_run_id"] = Tracking(session, args.mlflow_arn).record(report, args.mlflow_bucket)
        save(args, s3, report, "evaluation")
    except Exception as error:
        report["passed"] = False
        report["error"] = type(error).__name__ + ": " + str(error)[:400]
        save(args, s3, report, "evaluation")
        raise
    finally:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["validate", "evaluate"])
    for name in ("release-id", "manifest-uri", "manifest-version", "manifest-sha256", "quarantine-bucket",
                 "evidence-bucket", "execution-id", "runtime-image", "policy-sha256", "evalset-sha256"):
        parser.add_argument("--" + name, required=True)
    for name in ("runtime-scan-uri", "runtime-scan-version", "runtime-scan-sha256", "scan-log-group",
                 "malware-plan-arn", "validation-uri", "mlflow-arn", "mlflow-bucket",
                 "runtime-exception-uri", "runtime-exception-version", "runtime-exception-sha256"):
        parser.add_argument("--" + name)
    parser.add_argument("--policy", default="/opt/astra/evaluation/policy.json")
    parser.add_argument("--dataset", default="/opt/astra/evaluation/cases.json")
    parser.add_argument("--model-directory", default="/opt/ml/processing/model")
    args = parser.parse_args()
    session = boto3.Session(region_name="us-east-1")
    (validate if args.stage == "validate" else evaluate_gpu)(args, session)


if __name__ == "__main__":
    main()
