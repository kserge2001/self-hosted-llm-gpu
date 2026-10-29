"""Build Gateway API routes with explicit HTTPS and browser authentication."""

import json
from pathlib import Path

import yaml

from render_manifest import render

ROOT = Path(__file__).resolve().parent


def browser_authentication(config, service, namespace):
    """Protect dashboards that use the shared browser identity provider."""
    auth = config["browser_auth"]
    parameters = auth["parameters"]
    settings = {
        "onUnauthenticatedRequest": "authenticate",
        "sessionCookieName": "Astra-" + service.replace("_", "-"),
        "sessionTimeout": 1800,
        "scope": "openid",
    }
    if auth["type"] == "cognito":
        settings.update({
            "userPoolArn": parameters["userPoolARN"],
            "userPoolClientId": parameters["userPoolClientID"],
            "userPoolDomain": parameters["userPoolDomain"],
        })
        action = {"type": "authenticate-cognito", "authenticateCognitoConfig": settings}
    else:
        for key in ("issuer", "authorizationEndpoint", "tokenEndpoint", "userInfoEndpoint"):
            settings[key] = parameters[key]
        settings["secret"] = {"name": parameters["secretName"]}
        action = {"type": "authenticate-oidc", "authenticateOIDCConfig": settings}
    return {
        "apiVersion": "gateway.k8s.aws/v1",
        "kind": "ListenerRuleConfiguration",
        "metadata": {"name": "astra-" + service.replace("_", "-") + "-auth", "namespace": namespace},
        "spec": {"actions": [action]},
    }


def build_resources(config, services, catalog):
    """Return the shared Gateway, backend settings and selected HTTPRoutes."""
    values = {
        "DOMAIN_NAME": config["domain_name"],
        "CLUSTER_NAME": config["cluster_name"],
        "ACM_CERTIFICATE_ARN": config["acm_certificate_arn"],
        "ALLOWED_CIDRS": json.dumps(config["allowed_cidrs"]),
    }
    template = (ROOT / "k8s/edge/gateway.yaml").read_text(encoding="utf-8")
    resources = list(yaml.safe_load_all(render(template, values)))
    backends = set()
    for service in sorted(set(services)):
        target = catalog[service]
        namespace = target["namespace"]
        name = "astra-" + service.replace("_", "-")
        # Both LiteLLM routes share one Service and one target-group configuration.
        backend = (namespace, target["service"])
        if backend not in backends:
            protocol = target.get("protocol", "HTTP")
            resources.append({
                "apiVersion": "gateway.k8s.aws/v1", "kind": "TargetGroupConfiguration",
                "metadata": {"name": "astra-" + target["service"], "namespace": namespace},
                "spec": {
                    "targetReference": {"name": target["service"], "kind": "Service"},
                    "defaultConfiguration": {
                        "targetType": "ip", "protocol": protocol,
                        "healthCheckConfig": {"healthCheckPath": target["health_path"], "healthCheckProtocol": protocol},
                    },
                },
            })
            backends.add(backend)
        rule = {
            "matches": [{"path": {"type": "PathPrefix", "value": target["path"]}}],
            "backendRefs": [{"name": target["service"], "port": target["port"]}],
        }
        # These dashboards handle their own logins. Model requests use keys.
        if service not in ("inference", "argocd", "grafana", "litellm"):
            authentication = browser_authentication(config, service, namespace)
            resources.append(authentication)
            rule["filters"] = [{
                "type": "ExtensionRef",
                "extensionRef": {"group": "gateway.k8s.aws", "kind": "ListenerRuleConfiguration", "name": authentication["metadata"]["name"]},
            }]
        resources.append({
            "apiVersion": "gateway.networking.k8s.io/v1", "kind": "HTTPRoute",
            "metadata": {"name": name, "namespace": namespace, "labels": {"astra/platform": config["cluster_name"]}},
            "spec": {
                "parentRefs": [{"name": "astra-public", "namespace": "platform-system", "sectionName": "https"}],
                "hostnames": [config["hosts"][service]],
                "rules": [rule],
            },
        })
    return resources
