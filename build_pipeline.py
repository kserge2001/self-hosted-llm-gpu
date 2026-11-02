"""Build a versionable SageMaker definition with isolated CPU/GPU roles."""

import argparse
import hashlib
import json
import re
from pathlib import Path


def get(path):
    return {"Get": path}


def join(*parts):
    return {"Std:Join": {"On": "", "Values": list(parts)}}


def result(path):
    return {"Std:JsonGet": {"PropertyFile": get("Steps.Evaluate.PropertyFiles.Evaluation"), "Path": path}}


def build(config, policy_sha256, evalset_sha256):
    for field in ("validation_image", "runtime_image"):
        if not re.fullmatch(r"\d{12}\.dkr\.ecr\.us-east-1\.amazonaws\.com/[^@]+@sha256:[a-f0-9]{64}", config[field]):
            raise ValueError("Pin an owned us-east-1 ECR image digest: " + field)
    for field in ("validation_role_arn", "evaluation_role_arn", "pipeline_role_arn"):
        if not re.fullmatch(r"arn:aws:iam::\d{12}:role/.+", config[field]):
            raise ValueError("Missing IAM role: " + field)
    if config["validation_role_arn"] == config["evaluation_role_arn"]:
        raise ValueError("Validation and GPU evaluation use separate roles")
    if not config["private_subnets"] or not config["security_groups"]:
        raise ValueError("Private Processing network configuration is required")
    if not re.fullmatch(r"[a-f0-9]{64}", config["runtime_scan"]["sha256"]):
        raise ValueError("Pin the runtime scan report")
    execution = get("Execution.PipelineExecutionId")
    root = join("s3://", config["evidence_bucket"], "/pipeline/", execution, "/")
    parameters = ["ReleaseId", "CandidateManifest", "CandidateManifestVersion", "CandidateManifestSha256"]
    common_args = [
        "--release-id", get("Parameters.ReleaseId"),
        "--manifest-uri", get("Parameters.CandidateManifest"),
        "--manifest-version", get("Parameters.CandidateManifestVersion"),
        "--manifest-sha256", get("Parameters.CandidateManifestSha256"),
        "--quarantine-bucket", config["quarantine_bucket"],
        "--evidence-bucket", config["evidence_bucket"], "--execution-id", execution,
        "--runtime-image", config["runtime_image"], "--policy-sha256", policy_sha256,
        "--evalset-sha256", evalset_sha256,
    ]

    def processing(name, stage, image, instance, role, extra, max_seconds, volume_kms=True):
        return {"Name": name, "Type": "Processing", "Arguments": {
            "AppSpecification": {"ImageUri": image, "ContainerEntrypoint": ["python3", "/opt/astra/pipeline_worker.py"],
                                 "ContainerArguments": [stage, *common_args, *extra]},
            "RoleArn": role,
            "Tags": [{"Key": "Project", "Value": "astra"},
                     {"Key": "AstraPipeline", "Value": config["pipeline_name"]}],
            "ProcessingResources": {"ClusterConfig": {"InstanceCount": 1, "InstanceType": instance,
                                     "VolumeSizeInGB": 150,
                                     **({"VolumeKmsKeyId": config["kms_key_arn"]} if volume_kms else {})}},
            "StoppingCondition": {"MaxRuntimeInSeconds": max_seconds},
            "NetworkConfig": {"EnableNetworkIsolation": False, "EnableInterContainerTrafficEncryption": True,
                              "VpcConfig": {"Subnets": config["private_subnets"], "SecurityGroupIds": config["security_groups"]}},
            "ProcessingOutputConfig": {"KmsKeyId": config["kms_key_arn"], "Outputs": [{
                "OutputName": "report", "S3Output": {"S3Uri": join(root, stage, "-output/"),
                "LocalPath": "/opt/ml/processing/output", "S3UploadMode": "EndOfJob"}}]},
        }}

    validation = processing("Validate", "validate", config["validation_image"], "ml.m5.xlarge",
                            config["validation_role_arn"], [
                                "--runtime-scan-uri", config["runtime_scan"]["uri"],
                                "--runtime-scan-version", config["runtime_scan"]["version"],
                                "--runtime-scan-sha256", config["runtime_scan"]["sha256"],
                                "--scan-log-group", config["scan_log_group"],
                                "--malware-plan-arn", config["malware_plan_arn"],
                            ], 1800)
    if config.get("runtime_exception"):
        exception = config["runtime_exception"]
        if not re.fullmatch(r"[a-f0-9]{64}", exception["sha256"]):
            raise ValueError("Pin the approved runtime exception")
        validation["Arguments"]["AppSpecification"]["ContainerArguments"].extend([
            "--runtime-exception-uri", exception["uri"], "--runtime-exception-version", exception["version"],
            "--runtime-exception-sha256", exception["sha256"],
        ])
    evaluation = processing("Evaluate", "evaluate", config["runtime_image"], "ml.g6e.2xlarge",
                            config["evaluation_role_arn"], [
                                "--validation-uri", join(root, "validation.json"),
                                "--mlflow-arn", config["mlflow_arn"], "--mlflow-bucket", config["mlflow_bucket"],
                            ], 3600, volume_kms=False)
    # g6e Processing uses hardware-encrypted local NVMe. SageMaker rejects a
    # customer KMS volume key for that storage; output encryption still uses KMS.
    evaluation["DependsOn"] = ["Validate"]
    evaluation["PropertyFiles"] = [{"PropertyFileName": "Evaluation", "OutputName": "report", "FilePath": "evaluation.json"}]
    metadata = {"release_id": result("release_id"), "manifest_sha256": result("subject.manifest_sha256"),
                "runtime_digest": result("subject.runtime_digest"), "evalset_sha256": result("subject.evalset_sha256"),
                "policy_sha256": result("subject.policy_sha256"), "evidence_uri": result("evidence.uri"),
                "evidence_version": result("evidence.version"), "evidence_sha256": result("evidence.sha256"),
                "mlflow_run_id": result("mlflow_run_id")}
    register = {"Name": "RegisterCandidate", "Type": "RegisterModel", "Arguments": {
        "ModelPackageGroupName": config["model_package_group"],
        "ModelPackageDescription": "Validated Astra candidate. Separate approval and publication are required.",
        "ModelApprovalStatus": "PendingManualApproval", "CustomerMetadataProperties": metadata,
        "InferenceSpecification": {"Containers": [{"Image": config["runtime_image"], "ModelDataSource": {
            "S3DataSource": {"S3Uri": result("model_source"), "S3DataType": "S3Prefix", "CompressionType": "None"}}}],
            "SupportedContentTypes": ["application/json"], "SupportedResponseMIMETypes": ["application/json"]},
        "ModelMetrics": {"ModelQuality": {"Statistics": {"ContentType": "application/json", "S3Uri": result("evidence.uri")}}},
    }}
    gate = {"Name": "RequirePassingEvaluation", "Type": "Condition", "DependsOn": ["Evaluate"], "Arguments": {
        "Conditions": [{"Type": "Equals", "LeftValue": result("passed"), "RightValue": True}],
        "IfSteps": [register], "ElseSteps": [{"Name": "RejectCandidate", "Type": "Fail",
            "Arguments": {"ErrorMessage": "Astra evaluation failed. No model package was registered or approved."}}],
    }}
    return {"Version": "2020-12-01", "Parameters": [{"Name": p, "Type": "String"} for p in parameters],
            "Steps": [validation, evaluation, gate]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    root = Path(__file__).resolve().parent
    hashes = [hashlib.sha256((root / "evaluation" / name).read_bytes()).hexdigest() for name in ("policy.json", "cases.json")]
    definition = build(config, *hashes)
    Path(args.output).write_text(json.dumps(definition, indent=2), encoding="utf-8")
    print("Wrote pipeline definition; no AWS resources were created.")


if __name__ == "__main__":
    main()
