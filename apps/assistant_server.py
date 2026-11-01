"""Authenticated classroom UI for one read-only assistant."""

import hashlib
import os
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import mlflow
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from apps.alb_auth import authenticated_user
from apps.astra_client import make_client
from apps.assistant_tools import dispatch, schema_json, tool_schema
from apps.traced_assistant import traced_ask


@asynccontextmanager
async def lifespan(app):
    kind = os.environ["ASSISTANT_KIND"]
    app.state.tools = tool_schema(kind)
    os.environ["TOOL_SCHEMA_SHA256"] = hashlib.sha256(schema_json(kind).encode()).hexdigest()
    for name in ("PROMPT_SHA256", "EVALSET_SHA256"):
        if not re.fullmatch(r"[a-f0-9]{64}", os.environ[name]):
            raise ValueError("Missing pinned identity: " + name)
    if not re.fullmatch(r"prompts:/[A-Za-z0-9_.-]+/[1-9][0-9]*", os.environ["PROMPT_URI"]):
        raise ValueError("Pin a numeric prompt version")
    if not re.fullmatch(r".+@sha256:[a-f0-9]{64}", os.environ["APP_IMAGE"]):
        raise ValueError("Pin the application image digest")
    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_ARN"])
    mlflow.set_registry_uri(os.environ["MLFLOW_TRACKING_ARN"])
    # The release bundles the reviewed prompt and experiment identity. Starting
    # an existing release must not call the registry or require MLflow uptime.
    if not os.environ.get("MLFLOW_EXPERIMENT_ID"):
        raise ValueError("Missing release experiment identity")
    app.state.prompt = Path(os.environ["PROMPT_FILE"]).read_bytes().decode("utf-8")
    if hashlib.sha256(app.state.prompt.encode()).hexdigest() != os.environ["PROMPT_SHA256"]:
        raise ValueError("Prompt content differs from the reviewed release")
    if kind == "kubernetes":
        from kubernetes import config
        config.load_incluster_config()
    app.state.client = make_client()
    app.state.slots = threading.BoundedSemaphore(4)
    app.state.kind = kind
    yield
    app.state.client.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


@app.get("/health")
def health():
    return {"ready": hasattr(app.state, "client")}


@app.get("/", response_class=HTMLResponse)
def index(x_amzn_oidc_data: str = Header(default="")):
    authenticated_user(x_amzn_oidc_data)
    return Path(__file__).with_name("assistant.html").read_text(encoding="utf-8").replace('data-preview="true"', 'data-preview="false"', 1)


@app.post("/ask")
def ask(value: Question, x_amzn_oidc_data: str = Header(default="")):
    user = hashlib.sha256(authenticated_user(x_amzn_oidc_data).encode()).hexdigest()
    if not app.state.slots.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Assistant is busy. Try again shortly.")
    try:
        return traced_ask(app.state.client, app.state.tools,
                          lambda name, arguments: dispatch(app.state.kind, name, arguments),
                          app.state.prompt, value.question, user)
    except Exception:
        # MLflow keeps the failure status; do not expose SDK errors or credentials.
        raise HTTPException(status_code=502, detail="The request could not be completed. Check the service trace.") from None
    finally:
        app.state.slots.release()
