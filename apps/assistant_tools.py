"""Small read-only tools, with permissions enforced before SDK calls."""

import json
import re


def tool_schema(kind):
    if kind == "kubernetes":
        tools = []
        for name, description in (
            ("list_pods", "Read pod status in the synthetic namespace."),
            ("describe_deployment", "Read readiness and conditions of a named synthetic deployment."),
            ("recent_events", "Read recent Kubernetes events in the synthetic namespace."),
        ):
            properties = {"namespace": {"type": "string", "enum": ["synthetic"]}}
            if name == "describe_deployment":
                properties["name"] = {"type": "string", "minLength": 1, "maxLength": 253}
            tools.append({"type": "function", "function": {"name": name, "description": description,
                          "parameters": {"type": "object", "properties": properties,
                                         "required": list(properties), "additionalProperties": False}}})
        return tools
    elif kind == "aws":
        name, description = "list_instances", "Read the state of Astra-tagged EC2 instances."
        parameters = {"type": "object", "properties": {}, "additionalProperties": False}
    else:
        raise ValueError("Unknown assistant kind")
    return [{"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}]


def dispatch(kind, name, arguments):
    if kind == "kubernetes" and name in {"list_pods", "describe_deployment", "recent_events"}:
        expected = {"namespace", "name"} if name == "describe_deployment" else {"namespace"}
        if (not isinstance(arguments, dict) or set(arguments) != expected
                or arguments.get("namespace") != "synthetic"):
            raise ValueError("Arguments are outside this assistant's read-only permissions")
        if name == "describe_deployment":
            deployment = arguments["name"]
            if (not isinstance(deployment, str) or len(deployment) > 253
                    or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*", deployment)):
                raise ValueError("Invalid deployment name")
        from kubernetes import client
        try:
            if name == "describe_deployment":
                item = client.AppsV1Api().read_namespaced_deployment(deployment, "synthetic", _request_timeout=10)
                return {"name": item.metadata.name, "generation": item.metadata.generation,
                        "observed_generation": item.status.observed_generation,
                        "desired_replicas": item.spec.replicas, "ready_replicas": item.status.ready_replicas or 0,
                        "available_replicas": item.status.available_replicas or 0,
                        "conditions": [{"type": c.type, "status": c.status, "reason": c.reason,
                                        "message": (c.message or "")[:300]} for c in (item.status.conditions or [])[:10]]}
            if name == "recent_events":
                # Bound pagination and output. Do not claim a truncated sample is complete.
                items, token = [], None
                for _ in range(3):
                    response = client.CoreV1Api().list_namespaced_event(
                        "synthetic", limit=100, _continue=token, _request_timeout=10)
                    items.extend(response.items)
                    token = response.metadata._continue
                    if not token:
                        break
                def timestamp(item):
                    value = item.last_timestamp or item.event_time or item.metadata.creation_timestamp
                    return value.isoformat() if value else ""
                items.sort(key=timestamp, reverse=True)
                return {"truncated": bool(token) or len(items) > 20, "events": [
                    {"object": e.involved_object.name, "kind": e.involved_object.kind,
                     "type": e.type, "reason": e.reason, "message": (e.message or "")[:300],
                     "count": e.count, "last_seen": timestamp(e)} for e in items[:20]]}
            response = client.CoreV1Api().list_namespaced_pod("synthetic", limit=30, _request_timeout=10)
        except client.ApiException as error:
            return {"error": "Kubernetes tool unavailable", "status": error.status}
        return [{"name": p.metadata.name, "phase": p.status.phase,
                 "conditions": [{"type": c.type, "status": c.status, "reason": c.reason,
                                  "message": (c.message or "")[:300]} for c in (p.status.conditions or [])[:5]]}
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
