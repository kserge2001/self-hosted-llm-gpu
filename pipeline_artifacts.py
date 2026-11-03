"""Version-bound model artifacts shared by file checks and publication."""

import hashlib
import json
import re
from urllib.parse import urlsplit

from artifact_loader import MANIFEST_LIMIT, safe_path


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def s3_location(uri):
    parsed = urlsplit(uri)
    if (parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/")
            or parsed.query or parsed.fragment or parsed.username):
        raise ValueError("Use a bucket and object key in an S3 URI")
    return parsed.netloc, parsed.path.lstrip("/")


def read_pinned_json(s3, uri, version, sha256, limit=MANIFEST_LIMIT):
    if not version or version == "null" or not re.fullmatch(r"[a-f0-9]{64}", sha256):
        raise ValueError("An object version and SHA-256 are required")
    bucket, key = s3_location(uri)
    response = s3.get_object(Bucket=bucket, Key=key, VersionId=version)
    with response["Body"] as source:
        raw = source.read(limit + 1)
    if len(raw) > limit or hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError("Pinned artifact integrity check failed")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object")
    return result


def put_json(s3, bucket, key, value, **extra):
    body = canonical_json(value)
    result = s3.put_object(Bucket=bucket, Key=key, Body=body,
                           ContentType="application/json", **extra)
    version = result.get("VersionId")
    if not version or version == "null":
        raise ValueError("The artifact bucket must have versioning enabled")
    return {"uri": f"s3://{bucket}/{key}", "version": version,
            "sha256": hashlib.sha256(body).hexdigest()}


def validate_candidate(candidate, release_id, quarantine_bucket):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", release_id):
        raise ValueError("Invalid release ID")
    if (candidate.get("schema") != 1 or candidate.get("release_id") != release_id
            or candidate.get("status") != "quarantine_unapproved"
            or candidate.get("bucket") != quarantine_bucket):
        raise ValueError("Candidate identity or quarantine bucket mismatch")
    if not re.fullmatch(r"[a-f0-9]{40}", candidate.get("source_revision", "")):
        raise ValueError("An immutable source revision is required")
    if not re.fullmatch(r"[\w-]+/[\w.-]+", candidate.get("source_repository", "")):
        raise ValueError("Invalid publisher repository")
    files = candidate.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Candidate has no files")
    names = set()
    prefixes = set()
    for item in files:
        name = item.get("path")
        safe_path(name)
        if name in names:
            raise ValueError("Duplicate candidate path")
        names.add(name)
        if not item.get("key", "").startswith(f"candidates/{release_id}/"):
            raise ValueError("Candidate object belongs to another release")
        if not item["key"].endswith("/" + name):
            raise ValueError("Candidate object path differs from its inventory")
        prefixes.add(item["key"][:-len(name)])
        if not item.get("version_id") or item["version_id"] == "null":
            raise ValueError("Candidate object needs a version")
        if not re.fullmatch(r"[a-f0-9]{64}", item.get("sha256", "")):
            raise ValueError("Candidate object needs a SHA-256")
        if type(item.get("bytes")) is not int or item["bytes"] <= 0:
            raise ValueError("Invalid candidate object size")
    if "config.json" not in names or not any(n.endswith(".safetensors") for n in names):
        raise ValueError("Candidate has no configuration or safetensors weights")
    if len(prefixes) != 1:
        raise ValueError("Candidate combines different upload attempts")
    return files


def runtime_findings(report, runtime_image):
    """Retain all HIGH/CRITICAL findings; no implicit exceptions or ignores."""
    digests = report.get("Metadata", {}).get("RepoDigests", [])
    if report.get("ArtifactName") != runtime_image and runtime_image not in digests:
        raise ValueError("Runtime scan belongs to another image")
    if (report.get("ArtifactType") != "container_image"
            or not isinstance(report.get("Results"), list) or not report["Results"]):
        raise ValueError("Incomplete container scan report")
    return [v for result in report["Results"]
            for v in result.get("Vulnerabilities", [])
            if v.get("Severity") in {"HIGH", "CRITICAL"}]
