"""Small read-only tools, with permissions enforced before SDK calls."""

import json


def tool_schema(kind):
    if kind == "kubernetes":
        name, description = "list_pods", "Read pod status in the synthetic namespace."
        parameters = {"type": "object", "properties": {"namespace": {"type": "string", "enum": ["synthetic"]}},
                      "required": ["namespace"], "additionalProperties": False}
    elif kind == "aws":
        name, description = "list_instances", "Read the state of Astra-tagged EC2 instances."
        parameters = {"type": "object", "properties": {}, "additionalProperties": False}
    else:
        raise ValueError("Unknown assistant kind")
    return [{"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}]


def dispatch(kind, name, arguments):
    if kind == "kubernetes" and name == "list_pods" and arguments == {"namespace": "synthetic"}:
        from kubernetes import client
        try:
            response = client.CoreV1Api().list_namespaced_pod("synthetic", limit=30, _request_timeout=10)
        except client.ApiException as error:
            return {"error": "Kubernetes tool unavailable", "status": error.status}
        return [{"name": p.metadata.name, "phase": p.status.phase,
                 "conditions": [{"type": c.type, "status": c.status, "reason": c.reason,
                                  "message": (c.message or "")[:300]} for c in (p.status.conditions or [])]}
                for p in response.items]
    if kind == "aws" and name == "list_instances" and arguments == {}:
        from apps.aws_tools import list_instances
        from botocore.exceptions import BotoCoreError, ClientError
        try:
            return list_instances()
        except (BotoCoreError, ClientError):
            return {"error": "AWS tool unavailable; instance state could not be verified"}
    raise ValueError("Tool name or arguments are outside this assistant's read-only permissions")


def schema_json(kind):
    return json.dumps(tool_schema(kind), sort_keys=True, separators=(",", ":"))
