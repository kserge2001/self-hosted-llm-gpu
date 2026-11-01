import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from prepare_deployment import prepare


class StoredManifest:
    def __init__(self, body):
        self.body = body

    def get_object(self, **arguments):
        return {"Body": io.BytesIO(self.body)}


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        digest = "a" * 64
        self.manifest = {"schema": 1, "release_id": "astra-test", "runtime_image": "example/runtime@sha256:" + digest,
                         "subject": {"runtime_digest": "sha256:" + digest, "evalset_sha256": "b" * 64},
                         "files": [{"path": name, "key": "releases/astra-test/files/" + name,
                                    "version_id": "version", "sha256": "c" * 64, "bytes": 5}
                                   for name in ["config.json", "model.safetensors"]]}
        self.config = {"release": {"uri": "s3://astra-release/releases/astra-test/release-manifest.json", "version": "manifest-version"},
                       "release_bucket": "astra-release", "loader_image": "example/loader@sha256:" + digest,
                       "serving_role_arn": "arn:aws:iam::123456789012:role/serving", "git_revision": "d" * 40,
                       "assistant_image": "example/assistant@sha256:" + digest, "mlflow_arn": "arn:aws:sagemaker:us-east-1:123456789012:mlflow-tracking-server/test",
                       "astra_host": "astra.example.com", "alb_arn": "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/test/abc",
                       "cognito_client_id": "test-client", "assistant_roles": {name: "arn:aws:iam::123456789012:role/" + name for name in ["k8s-assistant", "aws-assistant"]},
                       "prompts": {kind: {"uri": "prompts:/astra-" + kind + "/1", "template": "Reviewed\nprompt: sample",
                                          "sha256": hashlib.sha256(b"Reviewed\nprompt: sample").hexdigest(), "experiment_id": "42"}
                                   for kind in ["kubernetes", "aws"]}}

    def render(self, root):
        body = json.dumps(self.manifest).encode()
        self.config["release"]["sha256"] = hashlib.sha256(body).hexdigest()
        return prepare(StoredManifest(body), self.config, root)

    def test_pins_model_and_keeps_assistant_identities_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.render(directory)
            self.assertFalse(result["deployed"])
            for name in ["k8s-assistant", "aws-assistant"]:
                docs = list(yaml.safe_load_all((Path(directory) / "assistants" / (name + ".yaml")).read_text()))
                service_account = next(doc for doc in docs if doc["kind"] == "ServiceAccount")
                self.assertEqual(service_account["metadata"]["annotations"]["eks.amazonaws.com/role-arn"], self.config["assistant_roles"][name])
                deployment = next(doc for doc in docs if doc["kind"] == "Deployment")
                self.assertEqual(deployment["spec"]["template"]["spec"]["serviceAccountName"], name)
                config = next(doc for doc in docs if doc["kind"] == "ConfigMap")
                self.assertTrue(config["immutable"])
                self.assertEqual(config["data"]["prompt.txt"], "Reviewed\nprompt: sample")
                pod = deployment["spec"]["template"]["spec"]
                self.assertEqual(pod["volumes"][0]["configMap"]["name"], config["metadata"]["name"])

    def test_modified_prompt_bundle_is_rejected_before_writing(self):
        self.config["prompts"]["aws"]["template"] = "Unreviewed change"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "Bundled prompt differs"):
                self.render(directory)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_runtime_substitution_is_rejected_before_writing(self):
        self.manifest["subject"]["runtime_digest"] = "sha256:" + "f" * 64
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "Runtime differs"):
                self.render(directory)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_prompt_alias_is_rejected_before_writing(self):
        self.config["prompts"]["aws"]["uri"] = "prompts:/astra-aws@latest"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "numeric prompt"):
                self.render(directory)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
