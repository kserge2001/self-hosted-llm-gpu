"""Exercise the real assistant HTTP/MLflow integration using a synthetic model.

This is a local compatibility check, not proof of inference or SageMaker access.
"""

import hashlib
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mlflow
from fastapi.testclient import TestClient
from apps.assistant_server import app
from register_prompt import AWS_TEMPLATE, register_template


def main():
    with tempfile.TemporaryDirectory() as directory:
        uri = (Path(directory) / "mlruns").as_uri()
        mlflow.set_tracking_uri(uri)
        mlflow.set_registry_uri(uri)
        experiment = mlflow.set_experiment("astra-aws-assistant")
        prompt = register_template("astra-aws-system", AWS_TEMPLATE)
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Synthetic local response", tool_calls=[]))],
            usage=SimpleNamespace(total_tokens=12))
        settings = {"ASSISTANT_KIND": "aws", "APP_IMAGE": "example/assistant@sha256:" + "a" * 64,
                    "APP_VERSION": "local-test", "ASTRA_RELEASE_ID": "synthetic-release",
                    "PROMPT_URI": f"prompts:/{prompt.name}/{prompt.version}",
                    "PROMPT_SHA256": hashlib.sha256(AWS_TEMPLATE.encode()).hexdigest(),
                    "EVALSET_SHA256": "b" * 64, "MLFLOW_TRACKING_ARN": uri}
        with patch.dict(os.environ, settings), patch("apps.assistant_server.make_client", return_value=client):
            with TestClient(app) as http:
                assert http.get("/health").status_code == 200
                assert http.post("/ask", json={"question": "Check the lab"}).status_code == 401
                with patch("apps.assistant_server.authenticated_user", return_value="synthetic-user"):
                    response = http.post("/ask", json={"question": "Check the lab"})
                assert response.status_code == 200, response.text
                result = response.json()
                assert result["answer"] == "Synthetic local response"
                assert result["trace_id"], result
                mlflow.flush_trace_async_logging()
        traces = mlflow.search_traces(experiment_ids=[experiment.experiment_id], return_type="list")
        assert len(traces) == 1
        root = next(span for span in traces[0].data.spans if span.parent_id is None)
        for key in ("application_image", "prompt_uri", "prompt_sha256", "astra_release", "tool_schema_sha256", "evalset_sha256"):
            assert root.inputs[key], (key, root.inputs)
        assert "Check the lab" not in str(root.inputs)
        print("PASS: HTTP authentication, synthetic response, trace ID, and six release identifiers")
        print("Scope: local MLflow only; no real model or AWS service was exercised")


if __name__ == "__main__":
    main()
