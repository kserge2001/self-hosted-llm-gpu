"""Record evaluation results through SageMaker's signed MLflow REST API."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

from pipeline_artifacts import put_json, s3_location


class Tracking:
    def __init__(self, session, tracking_arn):
        parts = tracking_arn.split(":", 5)
        if len(parts) != 6 or parts[0:3] != ["arn", "aws", "sagemaker"] or not parts[5].startswith("mlflow-tracking-server/"):
            raise ValueError("Use the managed MLflow tracking server ARN")
        self.session, self.arn, self.region = session, tracking_arn, parts[3]
        self.endpoint = f"https://{self.region}.experiments.sagemaker.aws"

    def call(self, method, path, value=None):
        url = self.endpoint + "/api/2.0/mlflow/" + path
        body = None
        if method == "GET" and value:
            url += "?" + urllib.parse.urlencode(value)
        elif value is not None:
            body = json.dumps(value).encode()
        headers = {"Content-Type": "application/json", "x-mlflow-sm-tracking-server-arn": self.arn}
        signed = AWSRequest(method=method, url=url, data=body, headers=headers)
        credentials = self.session.get_credentials().get_frozen_credentials()
        SigV4Auth(credentials, "sagemaker-mlflow", self.region).add_auth(signed)
        request = urllib.request.Request(url, data=body, method=method, headers=dict(signed.headers))
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)

    def record(self, report, artifact_bucket):
        experiment_name = "astra-model-evaluation"
        try:
            experiment = self.call("GET", "experiments/get-by-name", {"experiment_name": experiment_name})["experiment"]
            experiment_id = experiment["experiment_id"]
        except urllib.error.HTTPError as error:
            detail = json.loads(error.read())
            if detail.get("error_code") != "RESOURCE_DOES_NOT_EXIST":
                raise
            experiment_id = self.call("POST", "experiments/create", {"name": experiment_name})["experiment_id"]
        now_ms = int(time.time() * 1000)
        tags = {"release_id": report["release_id"], **report["subject"],
                "mlflow.runName": report["release_id"], "scope": "synthetic-classroom-evaluation"}
        run = self.call("POST", "runs/create", {
            "experiment_id": experiment_id, "start_time": now_ms,
            "tags": [{"key": k, "value": v} for k, v in tags.items()],
        })["run"]["info"]
        run_id = run["run_id"]
        try:
            bucket, key = s3_location(run["artifact_uri"] + "/case-report.json")
            if bucket != artifact_bucket:
                raise ValueError("MLflow artifact store differs from the configured bucket")
            artifact = put_json(self.session.client("s3"), bucket, key, report)
            rows = report["evaluation"]["cases"]
            metrics = {"case_count": len(rows), "passed_cases": sum(row["passed"] for row in rows),
                       "pass_rate": sum(row["passed"] for row in rows) / len(rows),
                       "max_request_seconds": max(row["seconds"] for row in report["evaluation"]["load"])}
            self.call("POST", "runs/log-batch", {
                "run_id": run_id,
                "metrics": [{"key": k, "value": v, "timestamp": now_ms, "step": 0} for k, v in metrics.items()],
                "params": [], "tags": [{"key": "case_report_sha256", "value": artifact["sha256"]}],
            })
            self.call("POST", "runs/update", {"run_id": run_id, "end_time": int(time.time() * 1000),
                                                "status": "FINISHED" if report["passed"] else "FAILED"})
            return run_id
        except Exception:
            self.call("POST", "runs/update", {"run_id": run_id, "status": "FAILED", "end_time": int(time.time() * 1000)})
            raise
