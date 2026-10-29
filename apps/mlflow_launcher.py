"""Send signed-in engineers to the SageMaker-managed MLflow UI."""

import os
import boto3
from fastapi import FastAPI, Header
from fastapi.responses import RedirectResponse
from apps.alb_auth import authenticated_user

app = FastAPI()
sagemaker = boto3.client("sagemaker", region_name="us-east-1")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def launch(x_amzn_oidc_data: str = Header(default="")):
    authenticated_user(x_amzn_oidc_data)
    result = sagemaker.create_presigned_mlflow_tracking_server_url(
        TrackingServerName=os.environ["MLFLOW_TRACKING_SERVER_NAME"],
        ExpiresInSeconds=60,
        SessionExpirationDurationInSeconds=1800,
    )
    return RedirectResponse(
        result["AuthorizedUrl"],
        status_code=303,
        headers={"Cache-Control": "no-store"},
    )
