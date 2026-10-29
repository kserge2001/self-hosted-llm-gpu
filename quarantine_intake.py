"""Download pinned model files, verify their hashes and upload to quarantine."""

import argparse
import hashlib
import json
import re
import tempfile
import uuid
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

import boto3

from artifact_loader import safe_path
from model_intake import validate_identity

METADATA = {
    "config.json", "tokenizer_config.json", "tokenizer.json", "tokenizer.model",
    "vocab.json", "merges.txt", "chat_template.jinja", "generation_config.json",
    "model.safetensors.index.json", "LICENSE", "README.md",
}


def selected_files(candidate):
    """Accept data files only. Never download Python or pickle files."""
    validate_identity(candidate["source_repository"], candidate["source_revision"])
    weights = {item["path"]: item for item in candidate["weights"]}
    selected = []
    for name in candidate["inventory"]:
        safe_path(name)
        if name in METADATA or name in weights:
            selected.append(name)
    if not weights or not set(weights).issubset(selected):
        raise ValueError("Missing model weights")
    for item in weights.values():
        if (not item["path"].endswith(".safetensors")
                or not re.fullmatch(r"[a-f0-9]{64}", item.get("reported_sha256") or "")
                or type(item.get("reported_bytes")) is not int or item["reported_bytes"] <= 0):
            raise ValueError("Every weight file needs a publisher hash and size")
    return selected, weights


def download(url, destination, expected_hash=None, expected_bytes=None):
    """Keep one file on disk at a time and verify it before uploading."""
    digest = hashlib.sha256()
    size = 0
    limit = expected_bytes if expected_bytes is not None else 128 * 1024 * 1024
    request = Request(url, headers={"User-Agent": "CareCart-model-intake/1.0"})
    with urlopen(request, timeout=120) as source, destination.open("wb") as target:
        while chunk := source.read(4 * 1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise ValueError("Download exceeds the expected size")
            digest.update(chunk)
            target.write(chunk)
    checksum = digest.hexdigest()
    if expected_bytes is not None and size != expected_bytes:
        raise ValueError("Download size mismatch")
    if expected_hash is not None and checksum != expected_hash:
        raise ValueError("Download hash mismatch")
    return size, checksum


def run(candidate, bucket, release_id, s3):
    names, weights = selected_files(candidate)
    safe_path(release_id)
    if "/" in release_id:
        raise ValueError("Use a single release ID")
    prefix = f"candidates/{release_id}/{uuid.uuid4().hex}"
    source = f"https://huggingface.co/{candidate['source_repository']}/resolve/{candidate['source_revision']}"
    files = []
    with tempfile.TemporaryDirectory() as folder:
        local_file = Path(folder) / "download"
        for name in names:
            weight = weights.get(name, {})
            expected_hash = weight.get("reported_sha256") or candidate["downloaded_metadata_sha256"].get(name)
            size, checksum = download(source + "/" + quote(name, safe="/"), local_file,
                                      expected_hash, weight.get("reported_bytes"))
            key = prefix + "/" + name
            s3.upload_file(str(local_file), bucket, key, ExtraArgs={"Metadata": {"sha256": checksum}})
            version = s3.head_object(Bucket=bucket, Key=key)["VersionId"]
            files.append({"path": name, "key": key, "version_id": version, "bytes": size, "sha256": checksum})
            local_file.unlink()
            print(f"Verified and uploaded {name}: {size} bytes", flush=True)
    manifest = {"schema": 1, "release_id": release_id, "status": "quarantine_unapproved",
                "source_repository": candidate["source_repository"], "source_revision": candidate["source_revision"],
                "license_label": candidate["license_label"], "bucket": bucket, "files": files}
    body = json.dumps(manifest, sort_keys=True, indent=2).encode()
    key = prefix + "/candidate-manifest.json"
    result = s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")
    print(json.dumps({"manifest_uri": f"s3://{bucket}/{key}", "manifest_version": result["VersionId"],
                      "manifest_sha256": hashlib.sha256(body).hexdigest()}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--release-id", required=True)
    args = parser.parse_args()
    candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    run(candidate, args.bucket, args.release_id, boto3.client("s3", region_name="us-east-1"))
