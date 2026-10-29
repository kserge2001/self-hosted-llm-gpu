"""Require trusted GuardDuty results for every exact candidate object version."""

import argparse
import hashlib
import json
from urllib.parse import urlsplit

import boto3


def check_scans(manifest, events, account, plan_arn):
    """S3 tags are not evidence. Only the protected service-event log is used."""
    results = {}
    for event in events:
        if (event.get("source") != "aws.guardduty"
                or event.get("detail-type") != "GuardDuty Malware Protection Object Scan Result"
                or event.get("account") != account
                or plan_arn not in event.get("resources", [])):
            continue
        detail = event["detail"]
        obj = detail["s3ObjectDetails"]
        identity = (obj["bucketName"], obj["objectKey"], obj["versionId"])
        clean = (detail.get("scanStatus") == "COMPLETED"
                 and detail.get("scanResultDetails", {}).get("scanResultStatus") == "NO_THREATS_FOUND")
        results.setdefault(identity, []).append((clean, event["id"]))
    evidence = []
    for item in manifest["files"]:
        identity = (manifest["bucket"], item["key"], item["version_id"])
        scans = results.get(identity, [])
        if not scans:
            raise ValueError("Missing scan for " + item["path"])
        if not all(clean for clean, _ in scans):
            raise ValueError("Scan failed, skipped or found a threat: " + item["path"])
        evidence.append({"path": item["path"], "version_id": item["version_id"],
                         "event_ids": sorted({event_id for _, event_id in scans})})
    return evidence


def read_events(logs, log_group):
    events = []
    for page in logs.get_paginator("filter_log_events").paginate(logGroupName=log_group):
        for record in page.get("events", []):
            events.append(json.loads(record["message"]))
    return events


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-uri", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--log-group", required=True)
    parser.add_argument("--plan-arn", required=True)
    args = parser.parse_args()
    uri = urlsplit(args.manifest_uri)
    if uri.scheme != "s3":
        parser.error("Use an S3 manifest URI")
    session = boto3.Session(region_name="us-east-1")
    response = session.client("s3").get_object(Bucket=uri.netloc, Key=uri.path.lstrip("/"), VersionId=args.version)
    with response["Body"] as source:
        body = source.read(4 * 1024 * 1024 + 1)
    if len(body) > 4 * 1024 * 1024 or hashlib.sha256(body).hexdigest() != args.sha256:
        raise ValueError("Candidate manifest integrity check failed")
    manifest = json.loads(body)
    account = session.client("sts").get_caller_identity()["Account"]
    events = read_events(session.client("logs"), args.log_group)
    evidence = check_scans(manifest, events, account, args.plan_arn)
    print(json.dumps({"malware": "PASS", "files": evidence}, indent=2))
