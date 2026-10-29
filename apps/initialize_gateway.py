"""Create the LiteLLM database user and save application credentials in AWS."""

import json
import os
import secrets
from urllib.parse import quote

import boto3
import psycopg
from psycopg import sql


def main():
    client = boto3.client("secretsmanager", region_name="us-east-1")

    def read(name):
        metadata = client.describe_secret(SecretId=name)
        if not metadata.get("VersionIdsToStages"):
            return None
        return client.get_secret_value(SecretId=name)["SecretString"]

    model_secret = os.environ["MODEL_SECRET_ARN"]
    gateway_secret = os.environ["GATEWAY_SECRET_ARN"]
    model = read(model_secret)
    if model is None:
        model = json.dumps({"api-key": secrets.token_urlsafe(48)})
        client.put_secret_value(SecretId=model_secret, SecretString=model)

    existing = read(gateway_secret)
    if existing:
        settings = json.loads(existing)
    else:
        password = secrets.token_urlsafe(36)
        settings = {
            "DATABASE_PASSWORD": password,
            "DATABASE_URL": "postgresql://litellm_app:" + quote(password, safe="") + "@" + os.environ["POSTGRES_HOST"] + ":5432/litellm?sslmode=require&sslcert=/certs/rds-ca.pem&sslaccept=strict",
            "REDIS_URL": "rediss://:" + quote(read(os.environ["REDIS_SECRET_ARN"]), safe="") + "@" + os.environ["REDIS_HOST"] + ":6379/0",
            "LITELLM_MASTER_KEY": "sk-" + secrets.token_urlsafe(48),
            "LITELLM_SALT_KEY": secrets.token_urlsafe(48),
            "VLLM_API_KEY": json.loads(model)["api-key"],
            "UI_USERNAME": "astra-admin",
            "UI_PASSWORD": secrets.token_urlsafe(36),
            "PROXY_BASE_URL": "https://" + os.environ["LITELLM_HOST"],
        }
        # Save before changing the database so an interrupted job can reuse it.
        client.put_secret_value(SecretId=gateway_secret, SecretString=json.dumps(settings))

    admin = json.loads(read(os.environ["POSTGRES_ADMIN_SECRET_ARN"]))
    with psycopg.connect(
        host=os.environ["POSTGRES_HOST"], dbname="litellm",
        user=admin["username"], password=admin["password"],
        sslmode="verify-full", sslrootcert="/app/rds-ca.pem", autocommit=True,
    ) as connection:
        if not connection.execute("SELECT 1 FROM pg_roles WHERE rolname = 'litellm_app'").fetchone():
            connection.execute("CREATE ROLE litellm_app LOGIN")
        connection.execute(sql.SQL("ALTER ROLE litellm_app PASSWORD {}").format(sql.Literal(settings["DATABASE_PASSWORD"])))
        connection.execute("GRANT CONNECT, CREATE ON DATABASE litellm TO litellm_app")
        connection.execute("GRANT USAGE, CREATE ON SCHEMA public TO litellm_app")
    print("Gateway database user and Secrets Manager configuration initialized")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # A failed job must not write credentials or database connection strings to logs.
        print("Gateway initialization failed:", type(error).__name__)
        raise SystemExit(1)
