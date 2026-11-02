"""Publish a fully evaluated, registry-approved model; write its manifest last."""

import argparse
import hashlib

from artifact_loader import CHUNK_SIZE, validate_manifest
from pipeline_artifacts import put_json, read_pinned_json, s3_location, validate_candidate
from release_gate import release_decision


def verify_copy(s3, bucket, item):
    response = s3.get_object(Bucket=bucket, Key=item["key"], VersionId=item["version_id"])
    digest = hashlib.sha256()
    count = 0
    with response["Body"] as source:
        while chunk := source.read(CHUNK_SIZE):
            count += len(chunk)
            if count > item["bytes"]:
                raise ValueError("Promoted object exceeds its expected size")
            digest.update(chunk)
    if count != item["bytes"] or digest.hexdigest() != item["sha256"]:
        raise ValueError("Promoted object failed its integrity check")


def copy_version(s3, source_bucket, destination_bucket, item, key):
    """Copy the pinned source version, including model shards above 5 GiB."""
    source = {"Bucket": source_bucket, "Key": item["key"], "VersionId": item["version_id"]}
    if item["bytes"] <= 5 * 1024 ** 3:
        return s3.copy_object(Bucket=destination_bucket, Key=key, CopySource=source,
                              MetadataDirective="REPLACE", Metadata={"sha256": item["sha256"]},
                              TaggingDirective="REPLACE")
    upload = s3.create_multipart_upload(Bucket=destination_bucket, Key=key,
                                        Metadata={"sha256": item["sha256"]})
    upload_id = upload["UploadId"]
    try:
        parts = []
        part_size = 1024 ** 3
        for number, start in enumerate(range(0, item["bytes"], part_size), 1):
            end = min(start + part_size, item["bytes"]) - 1
            part = s3.upload_part_copy(Bucket=destination_bucket, Key=key,
                UploadId=upload_id, PartNumber=number, CopySource=source,
                CopySourceRange=f"bytes={start}-{end}")
            parts.append({"PartNumber": number, "ETag": part["CopyPartResult"]["ETag"]})
        return s3.complete_multipart_upload(Bucket=destination_bucket, Key=key,
            UploadId=upload_id, MultipartUpload={"Parts": parts})
    except Exception:
        s3.abort_multipart_upload(Bucket=destination_bucket, Key=key, UploadId=upload_id)
        raise


def promote(s3, sagemaker, package_arn, evidence_bucket, quarantine_bucket,
            release_bucket, package_group, now=None):
    package = sagemaker.describe_model_package(ModelPackageName=package_arn)
    if package.get("ModelPackageGroupName") != package_group:
        raise ValueError("Model package belongs to another group")
    if package.get("ModelPackageStatus") != "Completed":
        raise ValueError("Model package is not complete")
    metadata = package.get("CustomerMetadataProperties", {})
    reference = {k: metadata[k] for k in ("evidence_uri", "evidence_version", "evidence_sha256")}
    if s3_location(reference["evidence_uri"])[0] != evidence_bucket:
        raise ValueError("Model package references an untrusted evidence bucket")
    evidence = read_pinned_json(s3, reference["evidence_uri"],
                                reference["evidence_version"], reference["evidence_sha256"])
    expected = {k: metadata[k] for k in (
        "release_id", "manifest_sha256", "runtime_digest", "evalset_sha256", "policy_sha256"
    )}
    # Approval comes from the current registry response, never a stored report.
    decision_input = dict(evidence, registry_status=package.get("ModelApprovalStatus"))
    allowed, reasons = release_decision(decision_input, expected, now)
    if not allowed:
        raise ValueError("Release blocked: " + "; ".join(reasons))
    manifest_ref = evidence["candidate"]
    if (s3_location(manifest_ref["uri"])[0] != quarantine_bucket
            or manifest_ref["sha256"] != expected["manifest_sha256"]):
        raise ValueError("Candidate reference differs from approved evidence")
    candidate = read_pinned_json(s3, **{
        "uri": manifest_ref["uri"], "version": manifest_ref["version"],
        "sha256": manifest_ref["sha256"],
    })
    files = validate_candidate(candidate, expected["release_id"], quarantine_bucket)
    runtime_image = evidence["runtime_image"]
    if runtime_image.rsplit("@", 1)[-1] != expected["runtime_digest"]:
        raise ValueError("Runtime differs from approved evaluation")
    prefix = f"releases/{expected['release_id']}"
    promoted = []
    for item in files:
        key = f"{prefix}/files/{item['path']}"
        result = copy_version(s3, quarantine_bucket, release_bucket, item, key)
        version = result.get("VersionId")
        if not version or version == "null":
            raise ValueError("Release bucket versioning is required")
        copied = {**item, "key": key, "version_id": version}
        verify_copy(s3, release_bucket, copied)
        promoted.append(copied)
    manifest = {
        "schema": 1, "release_id": expected["release_id"],
        "runtime_image": runtime_image, "files": promoted,
        "source_repository": candidate["source_repository"],
        "source_revision": candidate["source_revision"],
        "license_label": candidate["license_label"],
        "model_package_arn": package_arn,
        "subject": evidence["subject"],
        "evidence": reference, "candidate": manifest_ref,
    }
    validate_manifest(manifest)
    # Never overwrite a completed release. An interrupted copy has no manifest.
    return put_json(s3, release_bucket, f"{prefix}/release-manifest.json",
                    manifest, IfNoneMatch="*")


def main():
    import boto3
    import json
    parser = argparse.ArgumentParser()
    for name in ("package-arn", "evidence-bucket", "quarantine-bucket", "release-bucket", "package-group"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    session = boto3.Session(region_name="us-east-1")
    result = promote(session.client("s3"), session.client("sagemaker"), **vars(args))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
