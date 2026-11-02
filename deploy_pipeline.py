"""Publish a pinned pipeline definition without starting any Processing job."""

import argparse
import hashlib
import json
from pathlib import Path

from build_pipeline import build


def deploy(client, config, definition):
    body = json.dumps(definition, sort_keys=True, separators=(",", ":"))
    arguments = {"PipelineName": config["pipeline_name"], "RoleArn": config["pipeline_role_arn"],
                 "PipelineDefinition": body, "ParallelismConfiguration": {"MaxParallelExecutionSteps": 1}}
    try:
        client.describe_pipeline(PipelineName=config["pipeline_name"])
    except client.exceptions.ResourceNotFound:
        response = client.create_pipeline(**arguments,
                                          Tags=[{"Key": "Project", "Value": "astra"}])
    else:
        response = client.update_pipeline(**arguments)
    version = response.get("PipelineVersionId")
    if version is None:
        versions = client.list_pipeline_versions(PipelineName=config["pipeline_name"], SortOrder="Descending", MaxResults=10)
        for item in versions["PipelineVersionSummaries"]:
            saved = client.describe_pipeline(PipelineName=config["pipeline_name"], PipelineVersionId=item["PipelineVersionId"])
            if json.loads(saved["PipelineDefinition"]) == definition:
                version = item["PipelineVersionId"]
                break
        if version is None:
            raise ValueError("Published definition could not be matched to an immutable pipeline version")
    return {"pipeline_arn": response["PipelineArn"], "pipeline_version": version,
            "definition_sha256": hashlib.sha256(body.encode()).hexdigest(), "execution_started": False}


def main():
    import boto3
    parser = argparse.ArgumentParser()
    parser.add_argument("config", help="Foundation model_pipeline output plus pinned images and scan reference")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    root = Path(__file__).resolve().parent
    policy_hash = hashlib.sha256((root / "model-policy.json").read_bytes()).hexdigest()
    definition = build(config, policy_hash)
    client = boto3.client("sagemaker", region_name="us-east-1")
    result = deploy(client, config, definition)
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
