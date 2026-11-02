"""Collect public model metadata. Never download or execute model weights."""

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

BASE = "https://huggingface.co"
LIMIT = 2 * 1024 * 1024


def fetch(path):
    """Read a small metadata file from Hugging Face."""
    request = Request(BASE + path, headers={"User-Agent": "CareCart-intake/1.0"})
    with urlopen(request, timeout=30) as response:
        data = response.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError("Metadata exceeds the 2 MiB limit")
    return data


def validate_identity(repo, revision):
    # Repository IDs look like publisher/model. A revision is a full Git hash.
    if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Use a publisher/model repository ID")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Use a full immutable 40-character commit hash")


def read_inventory(info):
    """Index the model's files, rejecting duplicate or unsafe filenames."""
    files = {}
    for item in info.get("siblings", []):
        name = item["rfilename"]
        if name in files or "\\" in name or ":" in name:
            raise ValueError("Unsafe or duplicate inventory path")
        for part in name.split("/"):
            if part in ("", ".", ".."):
                raise ValueError("Unsafe or duplicate inventory path")
        files[name] = item
    return files


def check_metadata(files, config, tokenizer):
    """Require the files needed to understand and load this candidate."""
    required = ["config.json", "tokenizer_config.json", "LICENSE", "README.md"]
    for filename in required:
        if filename not in files:
            raise ValueError("Missing required metadata files")

    has_tokenizer = False
    for filename in ["tokenizer.json", "tokenizer.model", "spiece.model"]:
        if filename in files:
            has_tokenizer = True
    has_vocabulary = "vocab.json" in files and "merges.txt" in files
    if not has_tokenizer and not has_vocabulary:
        raise ValueError("Tokenizer assets are missing")
    if "chat_template.jinja" not in files and not tokenizer.get("chat_template"):
        raise ValueError("Chat template needs review")
    if config.get("auto_map") or tokenizer.get("auto_map"):
        raise ValueError("Custom code mapping requires a separate review")


def read_weights(files):
    """Record weight filenames and sizes without downloading the weights."""
    weights = []
    for name, item in sorted(files.items()):
        if name.endswith(".safetensors"):
            size = item.get("size")
            if type(size) is not int or size <= 0:
                raise ValueError("Weight size is missing or invalid")
            weights.append(
                {
                    "path": name,
                    "reported_bytes": size,
                    "reported_sha256": item.get("lfs", {}).get("sha256"),
                }
            )
    if not weights:
        raise ValueError("No safetensors weights found")
    return weights


def make_manifest(repo, revision, info, config, tokenizer, metadata_hashes):
    """Check the source, inspect its files, then write the candidate record."""
    validate_identity(repo, revision)
    if info.get("sha") != revision or info.get("id") != repo:
        raise ValueError("Returned source identity does not match the request")
    files = read_inventory(info)
    check_metadata(files, config, tokenizer)
    weights = read_weights(files)
    model_card = info.get("cardData") or {}
    license_label = model_card.get("license")
    if not license_label:
        raise ValueError("License metadata needs review")

    total_weight_bytes = 0
    for weight in weights:
        total_weight_bytes += weight["reported_bytes"]
    quantization = config.get("quantization_config") or {}
    return {
        "alias": "astra",
        "status": "candidate_unapproved",
        "source_repository": repo,
        "source_revision": revision,
        "license_label": license_label,
        "license_review": "pending",
        "model_type": config.get("model_type"),
        "architectures": config.get("architectures", []),
        "quantization_method": quantization.get("quant_method"),
        "remote_code_allowed": False,
        "inventory": sorted(files),
        "weights": weights,
        "reported_weight_bytes": total_weight_bytes,
        "downloaded_metadata_sha256": metadata_hashes,
        "weights_downloaded": False,
        "weight_hashes_verified": False,
        "pending": [
            "license approval",
            "runtime compatibility",
            "GPU sizing",
            "artifact scans",
            "live serving response",
            "release approval",
        ],
    }


def collect(repo, revision):
    """Fetch the pinned metadata and turn it into an intake record."""
    validate_identity(repo, revision)
    raw_info = fetch(f"/api/models/{repo}/revision/{revision}?blobs=true")
    info = json.loads(raw_info)
    metadata = {}
    hashes = {"hub_inventory.json": hashlib.sha256(raw_info).hexdigest()}
    for name in ("config.json", "tokenizer_config.json", "LICENSE", "README.md"):
        data = fetch(f"/{repo}/resolve/{revision}/{name}")
        hashes[name] = hashlib.sha256(data).hexdigest()
        if name.endswith(".json"):
            metadata[name] = json.loads(data)
    result = make_manifest(
        repo,
        revision,
        info,
        metadata["config.json"],
        metadata["tokenizer_config.json"],
        hashes,
    )
    result["collected_at_utc"] = datetime.now(timezone.utc).isoformat()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", default="astra-candidate.json")
    args = parser.parse_args()
    if Path(args.output).exists():
        parser.error("Output exists; select a new filename to preserve evidence")
    try:
        manifest = collect(args.repo, args.revision)
        with open(args.output, "x", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2)
            stream.write("\n")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Intake failed: {error}\n")
    print(f"Saved {args.output}: candidate_unapproved; no weights downloaded")
