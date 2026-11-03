"""Prepare platform manifests from Terraform outputs and an owned image digest."""
import argparse
import json
import secrets
from pathlib import Path

from render_manifest import render

ROOT = Path(__file__).resolve().parent


def prepare(outputs, bootstrap_image, repository, revision, destination):
    values = {key: item["value"] for key, item in outputs.items()}
    app_secrets = values["application_secrets"]
    common = {"GITOPS_REPOSITORY_URL": repository, "GITOPS_REVISION": revision}
    gateway = dict(common,
        GATEWAY_BOOTSTRAP_IMAGE=bootstrap_image,
        GATEWAY_BOOTSTRAP_ROLE_ARN=values["gateway_bootstrap_role"],
        GATEWAY_SECRET_READER_ROLE_ARN=app_secrets["gateway"]["reader_role_arn"],
        GATEWAY_SECRET_ARN=app_secrets["gateway"]["secret_arn"],
        MODEL_SECRET_ARN=app_secrets["llm"]["secret_arn"],
        POSTGRES_ADMIN_SECRET_ARN=values["postgres_admin_secret"],
        POSTGRES_HOST=values["postgres_host"],
        REDIS_SECRET_ARN=values["redis_secret"], REDIS_HOST=values["redis_host"],
        LITELLM_HOST=values["domain_configuration"]["hosts"]["litellm"])
    documents = {
        "argocd-platform.yaml": render((ROOT / "argocd/platform.yaml").read_text(), common),
        "argocd-gateway.yaml": render((ROOT / "argocd/gateway.yaml").read_text(), gateway),
    }
    for namespace, secret in app_secrets.items():
        documents["secret-" + namespace + ".yaml"] = render(
            (ROOT / "k8s/secrets/application-secret.yaml").read_text(), {
                "NAMESPACE": namespace, "SECRET_READER_ROLE_ARN": secret["reader_role_arn"],
                "TARGET_SECRET_NAME": secret["target_name"], "SOURCE_SECRET_ARN": secret["secret_arn"]})
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for name, text in documents.items():
        path = destination / name
        if path.exists() and path.read_text(encoding="utf-8") != text:
            raise FileExistsError("Review the existing generated file before replacing it: " + str(path))
    for name, text in documents.items():
        (destination / name).write_text(text, encoding="utf-8")
    return values


def initialize_grafana(secret_arn):
    import boto3
    client = boto3.client("secretsmanager", region_name="us-east-1")
    try:
        value = json.loads(client.get_secret_value(SecretId=secret_arn)["SecretString"])
    except client.exceptions.ResourceNotFoundException:
        value = {"admin-user": "astra-admin", "admin-password": secrets.token_urlsafe(32)}
        client.put_secret_value(SecretId=secret_arn, SecretString=json.dumps(value))
    if not value.get("admin-user") or not value.get("admin-password"):
        raise ValueError("The existing Grafana secret is incomplete; review it in Secrets Manager")
    print("Grafana credentials are stored in Secrets Manager; no credential values are printed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs", default="foundation-outputs.json")
    parser.add_argument("--bootstrap-image", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--revision", default="main")
    parser.add_argument("--output", default="k8s/generated/platform")
    parser.add_argument("--initialize-grafana", action="store_true")
    args = parser.parse_args()
    outputs = json.loads(Path(args.outputs).read_bytes())
    values = prepare(outputs, args.bootstrap_image, args.repository, args.revision, args.output)
    if args.initialize_grafana:
        initialize_grafana(values["application_secrets"]["monitoring"]["secret_arn"])
    print("Platform manifests prepared. Bootstrap controllers, apply secrets and applications, then sync storage before monitoring.")
