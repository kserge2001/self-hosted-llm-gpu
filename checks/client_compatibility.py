"""Exercise local MLflow APIs. This does not test SageMaker or a model."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mlflow
from register_prompt import register_template


def main():
    with tempfile.TemporaryDirectory() as temp:
        store = Path(temp) / "mlruns"
        store.mkdir()
        mlflow.set_tracking_uri(store.as_uri())
        mlflow.set_registry_uri(store.as_uri())
        experiment = mlflow.set_experiment("local-compatibility")
        first = register_template()
        second = register_template(template="Updated synthetic prompt")
        assert first.version == 1 and second.version == 2
        assert mlflow.load_prompt(f"prompts:/{first.name}/1").template == first.template
        with mlflow.start_span(name="compatibility", span_type="CHAIN"):
            with mlflow.start_span(
                name="synthetic-model-call", span_type="LLM"
            ) as span:
                span.set_outputs({"synthetic": True})
            with mlflow.start_span(name="synthetic-tool", span_type="TOOL") as span:
                span.set_outputs({"synthetic": True})
        mlflow.flush_trace_async_logging()
        traces = mlflow.search_traces(
            experiment_ids=[experiment.experiment_id], return_type="list"
        )
        assert len(traces) == 1 and len(traces[0].data.spans) == 3
        print("PASS: local MLflow prompt versions, loading, and CHAIN/LLM/TOOL spans")
        print(
            "Scope: local library compatibility only; no SageMaker or inference tested"
        )


if __name__ == "__main__":
    main()
