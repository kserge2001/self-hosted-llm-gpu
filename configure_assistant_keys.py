"""Create model-scoped assistant keys and keep their values in Secrets Manager."""
import argparse
import json
from pathlib import Path

import boto3
import requests


def configure(outputs):
    values = {key: item["value"] for key, item in outputs.items()}
    secret_settings = values["application_secrets"]
    secrets = boto3.client("secretsmanager", region_name="us-east-1")
    master = json.loads(secrets.get_secret_value(
        SecretId=secret_settings["gateway"]["secret_arn"])["SecretString"])["LITELLM_MASTER_KEY"]
    base = "https://" + values["domain_configuration"]["hosts"]["litellm"]
    for name in ("k8s-assistant", "aws-assistant"):
        secret_arn = secret_settings[name]["secret_arn"]
        metadata = secrets.describe_secret(SecretId=secret_arn)
        if metadata.get("VersionIdsToStages"):
            existing = json.loads(secrets.get_secret_value(SecretId=secret_arn)["SecretString"])
            if not existing.get("OPENAI_API_KEY"):
                raise ValueError("Existing assistant secret is incomplete: " + name)
            print(name + ": kept existing key")
            continue
        response = requests.post(base + "/key/generate",
            headers={"Authorization": "Bearer " + master},
            json={"key_alias": name, "models": ["astra"], "rpm_limit": 20, "tpm_limit": 20000},
            timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f"Key creation failed for {name}: HTTP {response.status_code}")
        key = response.json().get("key")
        if not isinstance(key, str) or not key.startswith("sk-"):
            raise ValueError("The gateway did not return an application key")
        secrets.put_secret_value(SecretId=secret_arn, SecretString=json.dumps({"OPENAI_API_KEY": key}))
        print(name + ": model-scoped key saved in Secrets Manager")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs", default="foundation-outputs.json")
    args = parser.parse_args()
    configure(json.loads(Path(args.outputs).read_bytes()))
