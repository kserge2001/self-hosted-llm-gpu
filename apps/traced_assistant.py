"""Record the assistant request and its model/tool calls in MLflow."""

import os
import mlflow
from assistant_loop import run_loop

def traced_ask(client, tools, dispatch, prompt_text, question, user):
    with mlflow.start_span(name=os.environ["ASSISTANT_KIND"] + "_assistant", span_type="CHAIN") as trace:
        # Record release identifiers, not the user's question or tool output.
        trace.set_inputs(
            {
                "application_version": os.environ["APP_VERSION"],
                "prompt_uri": os.environ["PROMPT_URI"],
                "astra_release": os.environ["ASTRA_RELEASE_ID"],
                "application_image": os.environ["APP_IMAGE"],
                "prompt_sha256": os.environ["PROMPT_SHA256"],
                "tool_schema_sha256": os.environ["TOOL_SCHEMA_SHA256"],
            }
        )
        result = run_loop(
            client,
            tools,
            dispatch,
            prompt_text,
            question,
            user,
            span_factory=mlflow.start_span,
        )
        trace.set_outputs({"completed": True, "tools_used": result["tools_used"]})
        result["trace_id"] = getattr(trace, "trace_id", None) or getattr(trace, "request_id", None)
        return result
