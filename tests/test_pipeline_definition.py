import copy
import json
import unittest
from unittest.mock import Mock

import boto3
from botocore.stub import Stubber
from botocore.validate import validate_parameters

from build_pipeline import build
from deploy_pipeline import deploy


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "pipeline_name": "astra-test-model-release", "pipeline_role_arn": "arn:aws:iam::123456789012:role/pipeline",
            "validation_role_arn": "arn:aws:iam::123456789012:role/validation",
            "evaluation_role_arn": "arn:aws:iam::123456789012:role/evaluation",
            "validation_image": "123456789012.dkr.ecr.us-east-1.amazonaws.com/astra/validation@sha256:" + "a" * 64,
            "runtime_image": "123456789012.dkr.ecr.us-east-1.amazonaws.com/astra/runtime@sha256:" + "b" * 64,
            "private_subnets": ["subnet-12345678"], "security_groups": ["sg-12345678"],
            "kms_key_arn": "arn:aws:kms:us-east-1:123456789012:key/test-key",
            "quarantine_bucket": "astra-test-quarantine", "evidence_bucket": "astra-test-evidence",
            "runtime_scan": {"uri": "s3://astra-test-evidence/runtime/scan.json", "version": "scan-version", "sha256": "c" * 64},
            "scan_log_group": "/astra/test/model-scans", "malware_plan_arn": "arn:aws:guardduty:us-east-1:123456789012:malware-protection-plan/test",
            "mlflow_arn": "arn:aws:sagemaker:us-east-1:123456789012:mlflow-tracking-server/test",
            "mlflow_bucket": "astra-test-mlflow", "model_package_group": "astra-test",
        }
        self.definition = build(self.config, "d" * 64, "e" * 64)
        self.client = boto3.client("sagemaker", region_name="us-east-1", aws_access_key_id="testing", aws_secret_access_key="testing")

    def test_processing_arguments_match_aws_sdk_schema(self):
        def resolve(value):
            if isinstance(value, dict):
                if "Get" in value or "Std:Join" in value or "Std:JsonGet" in value:
                    return "resolved-value"
                return {k: resolve(v) for k, v in value.items()}
            if isinstance(value, list):
                return [resolve(v) for v in value]
            return value
        model = self.client.meta.service_model.operation_model("CreateProcessingJob")
        for step in self.definition["Steps"][:2]:
            arguments = resolve(step["Arguments"])
            arguments["ProcessingJobName"] = "astra-test-job"
            validate_parameters(arguments, model.input_shape)

    def test_unpinned_image_and_shared_role_fail(self):
        bad = copy.deepcopy(self.config)
        bad["runtime_image"] = bad["runtime_image"].split("@")[0] + ":latest"
        with self.assertRaises(ValueError):
            build(bad, "d" * 64, "e" * 64)
        bad = copy.deepcopy(self.config)
        bad["evaluation_role_arn"] = bad["validation_role_arn"]
        with self.assertRaises(ValueError):
            build(bad, "d" * 64, "e" * 64)

    def test_nvme_gpu_omits_unsupported_volume_key_but_keeps_output_encryption(self):
        validation, evaluation = self.definition["Steps"][:2]
        cpu = validation["Arguments"]["ProcessingResources"]["ClusterConfig"]
        gpu = evaluation["Arguments"]["ProcessingResources"]["ClusterConfig"]
        self.assertEqual(cpu["VolumeKmsKeyId"], self.config["kms_key_arn"])
        self.assertEqual(gpu["InstanceType"], "ml.g6e.2xlarge")
        self.assertNotIn("VolumeKmsKeyId", gpu)
        for step in (validation, evaluation):
            self.assertEqual(step["Arguments"]["ProcessingOutputConfig"]["KmsKeyId"], self.config["kms_key_arn"])

    def test_creation_finds_matching_version_without_starting_job(self):
        arn = "arn:aws:sagemaker:us-east-1:123456789012:pipeline/astra-test-model-release"
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        with Stubber(self.client) as stub:
            stub.add_client_error("describe_pipeline", service_error_code="ResourceNotFound", expected_params={"PipelineName": self.config["pipeline_name"]})
            stub.add_response("create_pipeline", {"PipelineArn": arn})
            stub.add_response("list_pipeline_versions", {"PipelineVersionSummaries": [{"PipelineVersionId": 1, "CreationTime": now}]})
            stub.add_response("describe_pipeline", {"PipelineArn": arn, "PipelineName": self.config["pipeline_name"],
                              "PipelineDefinition": json.dumps(self.definition), "RoleArn": self.config["pipeline_role_arn"],
                              "PipelineStatus": "Active", "CreationTime": now, "LastModifiedTime": now})
            result = deploy(self.client, self.config, self.definition)
            self.assertEqual(result["pipeline_version"], 1)
            self.assertFalse(result["execution_started"])
            stub.assert_no_pending_responses()


if __name__ == "__main__":
    unittest.main()
