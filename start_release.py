"""Start a pinned SageMaker workflow from a reviewed release request."""

import argparse
import hashlib
import json
import re

RELEASE_ID_PATTERN = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
REQUEST_FIELDS = {
    "release_id",
    "pipeline_version",
    "manifest_uri",
    "manifest_version",
    "manifest_sha256",
}


def validate_request(release_id, request):
    """Reject requests without an exact pipeline and model-manifest version."""
    if not isinstance(release_id, str) or not re.fullmatch(
        RELEASE_ID_PATTERN, release_id
    ):
        raise ValueError("Invalid release ID")
    if not isinstance(request, dict) or set(request) != REQUEST_FIELDS:
        raise ValueError("Release request has missing or unexpected fields")
    if request.get("release_id") != release_id:
        raise ValueError("Release request mismatch")
    if (
        type(request.get("pipeline_version")) is not int
        or request["pipeline_version"] < 1
    ):
        raise ValueError("Pin a pipeline version")
    if not isinstance(request["manifest_sha256"], str) or not re.fullmatch(
        r"[a-f0-9]{64}", request["manifest_sha256"]
    ):
        raise ValueError("Invalid manifest hash")
    if not isinstance(request["manifest_uri"], str) or not re.fullmatch(
        r"s3://[a-z0-9.-]+/[^\s]+", request["manifest_uri"]
    ):
        raise ValueError("Invalid S3 manifest URI")
    if (
        not isinstance(request["manifest_version"], str)
        or not request["manifest_version"].strip()
        or request["manifest_version"] == "null"
    ):
        raise ValueError("Pin an S3 object version")


def request_arguments(release_id, request, pipeline_name="astra-model-release"):
    """Build the SageMaker API arguments from a checked release request."""
    validate_request(release_id, request)
    if not re.fullmatch(r"[A-Za-z0-9](?:-*[A-Za-z0-9]){0,255}", pipeline_name):
        raise ValueError("Invalid pipeline name")
    # Repeating the same request uses the same token, avoiding duplicate runs.
    request_json = json.dumps(request, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(request_json.encode()).hexdigest()
    return {
        "PipelineName": pipeline_name,
        "PipelineVersionId": request["pipeline_version"],
        "PipelineExecutionDisplayName": release_id,
        "ClientRequestToken": digest,
        "PipelineParameters": [
            {"Name": "ReleaseId", "Value": release_id},
            {"Name": "CandidateManifest", "Value": request["manifest_uri"]},
            {"Name": "CandidateManifestVersion", "Value": request["manifest_version"]},
            {"Name": "CandidateManifestSha256", "Value": request["manifest_sha256"]},
        ],
    }


if __name__ == "__main__":
    import boto3

    parser = argparse.ArgumentParser()
    parser.add_argument("release_id")
    parser.add_argument("--pipeline-name", default="astra-model-release")
    args = parser.parse_args()
    if not re.fullmatch(RELEASE_ID_PATTERN, args.release_id):
        parser.error("Invalid release ID")
    from release_requests import load_request

    request = load_request(args.release_id)
    arguments = request_arguments(args.release_id, request, args.pipeline_name)
    sagemaker = boto3.client("sagemaker", region_name="us-east-1")
    # ** passes each dictionary entry as a named argument to the AWS SDK.
    response = sagemaker.start_pipeline_execution(**arguments)
    print(response["PipelineExecutionArn"])
