"""Render reviewable GitOps manifests from a pinned promoted release."""

import argparse
import hashlib
import json
import re
from pathlib import Path

import yaml

from artifact_loader import validate_manifest
from pipeline_artifacts import read_pinned_json
from render_manifest import render

ROOT = Path(__file__).resolve().parent


def prepare(s3, settings, output, component="all"):
    if component not in {"all", "model", "assistants"}:
        raise ValueError("Choose model, assistants or all")
    reference = settings["release"]
    manifest = read_pinned_json(s3, reference["uri"], reference["version"], reference["sha256"])
    validate_manifest(manifest)
    from pipeline_artifacts import s3_location
    bucket, key = s3_location(reference["uri"])
    if bucket != settings["release_bucket"] or key != f"releases/{manifest['release_id']}/release-manifest.json":
        raise ValueError("Use the expected promoted release bucket and manifest path")
    if manifest["runtime_image"].rsplit("@", 1)[-1] != manifest["subject"]["runtime_digest"]:
        raise ValueError("Runtime differs from the prepared release")
    common = {
        "RELEASE_ID": manifest["release_id"], "RUNTIME_IMAGE": manifest["runtime_image"],
        "RELEASE_BUCKET": bucket, "MANIFEST_KEY": key, "MANIFEST_VERSION": reference["version"],
        "MANIFEST_SHA256": reference["sha256"], "LOADER_IMAGE": settings["loader_image"],
        "SERVING_ROLE_ARN": settings["serving_role_arn"],
    }
    documents = {}
    if component in {"all", "model"}:
        documents["model/model.yaml"] = render((ROOT / "k8s/vllm.yaml").read_text(), common)
    if component in {"all", "assistants"}:
        common.update(APP_VERSION=settings["git_revision"], ASSISTANT_IMAGE=settings["assistant_image"],
            MLFLOW_TRACKING_ARN=settings["mlflow_arn"],
            ASTRA_HOST=settings["astra_host"], EXPECTED_ALB_ARN=settings["alb_arn"],
            COGNITO_CLIENT_ID=settings["cognito_client_id"])
    if component != "model" and not re.fullmatch(r"[a-f0-9]{40}", common["APP_VERSION"]):
        raise ValueError("Pin the application source commit")
    assistants = (("kubernetes", "k8s-assistant"), ("aws", "aws-assistant")) if component != "model" else ()
    for kind, name in assistants:
        prompt = settings["prompts"][kind]
        if not re.fullmatch(r"prompts:/[A-Za-z0-9_.-]+/[1-9][0-9]*", prompt["uri"]):
            raise ValueError("Pin a numeric prompt version")
        if not re.fullmatch(r"[a-f0-9]{64}", prompt["sha256"]):
            raise ValueError("Pin the prompt content hash")
        if (not isinstance(prompt.get("template"), str) or not prompt["template"]
                or hashlib.sha256(prompt["template"].encode()).hexdigest() != prompt["sha256"]):
            raise ValueError("Bundled prompt differs from the reviewed content hash")
        experiment_id = str(prompt.get("experiment_id", ""))
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", experiment_id):
            raise ValueError("Pin the MLflow experiment identity")
        prompt_config = name + "-prompt-" + prompt["sha256"][:16]
        values = dict(common, ASSISTANT_NAME=name, ASSISTANT_KIND=kind,
                      ASSISTANT_ROLE_ARN=settings["assistant_roles"][name],
                      PROMPT_URI=prompt["uri"], PROMPT_SHA256=prompt["sha256"],
                      PROMPT_CONFIG=prompt_config, MLFLOW_EXPERIMENT_ID=experiment_id)
        documents[f"assistants/{name}.yaml"] = (
            render((ROOT / "k8s/assistant.yaml").read_text(), values)
            + "\n---\n" + yaml.safe_dump({"apiVersion": "v1", "kind": "ConfigMap",
                "metadata": {"name": prompt_config, "namespace": name}, "immutable": True,
                "data": {"prompt.txt": prompt["template"]}}, sort_keys=False))
    if component != "model":
        documents["assistants/tool-permissions.yaml"] = (
            "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: synthetic\n---\n"
            + (ROOT / "k8s/assistant-rbac.yaml").read_text())
    # Validate every document and destination before writing any file.
    output = Path(output)
    for relative, text in documents.items():
        if (output / relative).exists():
            raise FileExistsError("Review the existing rendered release before replacing it: " + relative)
        for document in yaml.safe_load_all(text):
            if not isinstance(document, dict) or not document.get("kind") or not document.get("metadata", {}).get("name"):
                raise ValueError("Invalid rendered Kubernetes resource")
    for relative, text in documents.items():
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return {"release_id": manifest["release_id"], "manifest": reference,
            "files": {name: hashlib.sha256(text.encode()).hexdigest() for name, text in documents.items()},
            "deployed": False}


def main():
    import boto3
    parser = argparse.ArgumentParser()
    parser.add_argument("config", nargs="?", help="Complete deployment settings for assistants or an existing workflow")
    parser.add_argument("--output", default="deploy")
    parser.add_argument("--component", choices=["all", "model", "assistants"], default="all")
    parser.add_argument("--release", help="Promoted-release record for the first model deployment")
    parser.add_argument("--outputs", default="foundation-outputs.json")
    parser.add_argument("--images", default="evidence/images.json")
    args = parser.parse_args()
    if args.release:
        if args.config or args.component != "model":
            parser.error("Use --release with --component model and no settings file")
        foundation = {k: v["value"] for k, v in json.loads(Path(args.outputs).read_bytes()).items()}
        images = json.loads(Path(args.images).read_bytes())
        settings = {"release": json.loads(Path(args.release).read_bytes()),
                    "release_bucket": foundation["buckets"]["release"],
                    "loader_image": images["loader"]["image"],
                    "serving_role_arn": foundation["serving_role_arn"]}
    elif args.config:
        settings = json.loads(Path(args.config).read_bytes())
    else:
        parser.error("Provide a settings file or --component model --release RECORD")
    print(json.dumps(prepare(boto3.client("s3", region_name="us-east-1"), settings, args.output, args.component), indent=2))


if __name__ == "__main__":
    main()
