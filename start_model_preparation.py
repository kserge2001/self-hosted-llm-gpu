"""Start the supplied CPU model-preparation workflow from exact input versions."""

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



def main():
    import boto3
    import os
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request-env', default='ASTRA_MODEL_REQUEST',
                        help='Environment variable containing the preparation input JSON')
    parser.add_argument('--pipeline-name', default='astra-model-release')
    args = parser.parse_args()
    request = json.loads(os.environ[args.request_env])
    arguments = request_arguments(request.get('release_id'), request, args.pipeline_name)
    client = boto3.client('sagemaker', region_name='us-east-1')
    print(client.start_pipeline_execution(**arguments)['PipelineExecutionArn'])


if __name__ == '__main__':
    main()
