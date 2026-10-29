"""Render and apply service routes from the applied Terraform configuration.

Render is local only. Apply requires the matching private EKS API, deployed
backend Services and a ready AWS Load Balancer Controller.
"""

import argparse
import ipaddress
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

from render_manifest import render
from gateway_routes import build_resources

ROOT = Path(__file__).resolve().parent
DNS = "external-dns.alpha.kubernetes.io/"


def command(argv):
    """Run a command and return its text output; stop if it fails."""
    result = subprocess.run(argv, check=True, capture_output=True, text=True)
    return result.stdout


def read_config(path=None):
    """Read the service addresses from a saved file or Terraform output."""
    if path:
        raw = Path(path).read_text(encoding="utf-8-sig")
    else:
        raw = command(
            [
                "terraform",
                f"-chdir={ROOT / 'infra'}",
                "output",
                "-json",
                "domain_configuration",
            ]
        )
    return json.loads(raw)


def catalog():
    """Load each service's namespace, port and route from YAML."""
    text = (ROOT / "k8s/edge/services.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def validate(config):
    """Check the hostnames, network allowlist, certificate and sign-in settings."""
    if set(config["hosts"]) != set(catalog()):
        raise ValueError(
            "Terraform hosts must contain exactly the seven supported services"
        )
    domain = config["domain_name"]
    label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    if not re.fullmatch(rf"{label}(?:\.{label})+", domain) or len(domain) > 180:
        raise ValueError("Invalid base domain")
    if len(set(config["hosts"].values())) != len(catalog()):
        raise ValueError("Each service must have a different hostname")
    for host in config["hosts"].values():
        if not re.fullmatch(rf"{label}\.{re.escape(domain)}", host):
            raise ValueError(f"Hostname must be one label beneath {domain}: {host}")
    if not config["allowed_cidrs"]:
        raise ValueError("An approved source CIDR is required")
    for cidr in config["allowed_cidrs"]:
        network = ipaddress.ip_network(cidr, strict=True)
        if network.version != 4 or network.prefixlen == 0:
            raise ValueError("Only explicit IPv4 source CIDRs are supported")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,26}", config["cluster_name"]):
        raise ValueError("Use a lowercase cluster name, at most 27 characters")
    if not re.fullmatch(
        r"arn:aws:acm:us-east-1:\d{12}:certificate/[a-f0-9-]+",
        config["acm_certificate_arn"],
    ):
        raise ValueError("The ACM certificate must be in us-east-1")
    auth = config.get("browser_auth")
    if auth:
        required = {
            "cognito": {"userPoolARN", "userPoolClientID", "userPoolDomain"},
            "oidc": {
                "issuer",
                "authorizationEndpoint",
                "tokenEndpoint",
                "userInfoEndpoint",
                "secretName",
            },
        }
        if (
            auth["type"] not in required
            or set(auth["parameters"]) != required[auth["type"]]
        ):
            raise ValueError(
                "Invalid browser sign-in settings; do not put secrets in tfvars"
            )
        for name, value in auth["parameters"].items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Browser sign-in settings cannot be empty")
            if auth["type"] == "oidc" and name != "secretName":
                if not value.startswith("https://"):
                    raise ValueError("OIDC endpoints must use HTTPS")


def build_routes(config, services):
    """Validate inputs before creating Gateway API configuration."""
    validate(config)
    routes = catalog()
    if not services:
        raise ValueError("Select supported service keys")
    for service in services:
        if service not in routes:
            raise ValueError("Select supported service keys")
        if service not in ("inference", "argocd", "grafana") and not config.get("browser_auth"):
            raise ValueError("Set approved browser_auth before publishing browser services")
    return build_resources(config, services, routes)


def render_bundle(config, services, directory):
    """Write the generated YAML and endpoint list without changing AWS."""
    resources = build_routes(config, services)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    values = {}
    for key in [
        "domain_name",
        "zone_id",
        "cluster_name",
        "txt_owner_id",
        "external_dns_role_arn",
    ]:
        values[key.upper()] = str(config[key])
    template = (ROOT / "k8s/edge/external-dns.yaml").read_text(encoding="utf-8")
    controller = render(template, values)
    (directory / "external-dns.yaml").write_text(controller, encoding="utf-8")
    (directory / "routes.yaml").write_text(
        yaml.safe_dump_all(resources, sort_keys=False), encoding="utf-8"
    )
    argocd = {
        "global": {"domain": config["hosts"]["argocd"]},
        "configs": {"cm": {"url": "https://" + config["hosts"]["argocd"]}},
        "server": {"ingress": {"enabled": False}},
    }
    monitoring = {
        "grafana": {
            "ingress": {"enabled": False},
            "grafana.ini": {
                "server": {
                    "domain": config["hosts"]["grafana"],
                    "root_url": "https://" + config["hosts"]["grafana"],
                }
            },
        }
    }
    for name, data in (
        ("argocd-domain-values.yaml", argocd),
        ("monitoring-domain-values.yaml", monitoring),
    ):
        (directory / name).write_text(
            yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
        )
    endpoints = {}
    for service, host in config["hosts"].items():
        endpoints[service] = "https://" + host
        if service == "inference":
            endpoints[service] += "/v1"
    (directory / "endpoints.json").write_text(
        json.dumps(endpoints, indent=2) + "\n", encoding="utf-8"
    )
    return resources


def assert_context(config, kube_config):
    """Prevent an apply to another cluster or through an unverified connection."""
    clusters = kube_config.get("clusters", [])
    if len(clusters) != 1:
        raise ValueError("Select exactly one Kubernetes cluster")
    current_cluster = clusters[0]["cluster"]
    current_endpoint = current_cluster["server"].rstrip("/")
    expected_endpoint = config["cluster_endpoint"].rstrip("/")
    if current_endpoint != expected_endpoint:
        raise ValueError(
            "Kubernetes context does not match this Terraform stack; nothing was applied"
        )
    if current_cluster.get("insecure-skip-tls-verify"):
        raise ValueError("Kubernetes API TLS verification must stay enabled")


def assert_certificate(config, cert, services):
    """Require an issued certificate that covers every selected hostname."""
    if cert["Status"] != "ISSUED":
        raise ValueError("The selected ACM certificate is not issued")
    names = list(cert.get("SubjectAlternativeNames", []))
    names.append(cert["DomainName"])
    for key in services:
        host = config["hosts"][key]
        wildcard = "*." + host.split(".", 1)[1]
        if host not in names and wildcard not in names:
            raise ValueError(f"The ACM certificate does not cover {host}")


def owns_dns_record(record, owner):
    """Check the ExternalDNS ownership label on a TXT record."""
    values = record.get("ResourceRecords", [])
    if record["Type"] != "TXT" or not values:
        return False
    for value in values:
        labels = value["Value"].strip('"').split(",")
        if owner not in labels:
            return False
    return True


def assert_dns_ownership(config, records, services):
    """Leave existing DNS records alone unless this stack owns them."""
    by_name = {}
    for record in records:
        name = record["Name"].rstrip(".")
        if name not in by_name:
            by_name[name] = []
        by_name[name].append(record)
    owner = "external-dns/owner=" + config["txt_owner_id"]
    for key in services:
        host = config["hosts"][key]
        ownership = []
        for kind in ("a", "aaaa", "cname"):
            ownership.extend(by_name.get(f"_astra-{kind}.{host}", []))
        owned = bool(ownership)
        for record in ownership:
            if not owns_dns_record(record, owner):
                owned = False
                break
        if (by_name.get(host) or ownership) and not owned:
            raise ValueError(
                f"DNS name is already in use without this stack's ownership: {host}"
            )


def preflight(config, services, context, run=command):
    """Check the deployment prerequisites before making any changes."""
    # 1. Match the Kubernetes connection to the Terraform cluster.
    kube = ["kubectl", "--context", context]
    assert_context(
        config, json.loads(run(kube + ["config", "view", "--minify", "-o", "json"]))
    )
    # 2. Check the certificate, public DNS zone and record ownership.
    aws = ["aws", "--region", "us-east-1", "--output", "json"]
    cert = json.loads(
        run(
            aws
            + [
                "acm",
                "describe-certificate",
                "--certificate-arn",
                config["acm_certificate_arn"],
            ]
        )
    )["Certificate"]
    assert_certificate(config, cert, services)
    zone = json.loads(
        run(aws + ["route53", "get-hosted-zone", "--id", config["zone_id"]])
    )["HostedZone"]
    if zone["Name"].rstrip(".") != config["domain_name"] or zone["Config"].get(
        "PrivateZone"
    ):
        raise ValueError("Route 53 zone is not the configured public domain")
    records = json.loads(
        run(
            aws
            + [
                "route53",
                "list-resource-record-sets",
                "--hosted-zone-id",
                config["zone_id"],
            ]
        )
    )["ResourceRecordSets"]
    assert_dns_ownership(config, records, services)
    # 3. Require Gateway API definitions, the controller and each backend Service.
    for name in ("gateways.gateway.networking.k8s.io", "httproutes.gateway.networking.k8s.io",
                 "loadbalancerconfigurations.gateway.k8s.aws", "listenerruleconfigurations.gateway.k8s.aws",
                 "targetgroupconfigurations.gateway.k8s.aws"):
        run(kube + ["get", "crd", name, "-o", "name"])
    controller = json.loads(
        run(
            kube
            + [
                "-n",
                "kube-system",
                "get",
                "deployment",
                "aws-load-balancer-controller",
                "-o",
                "json",
            ]
        )
    )
    if controller.get("status", {}).get("availableReplicas", 0) < 1:
        raise ValueError("AWS Load Balancer Controller is not ready")
    for key in services:
        route = catalog()[key]
        service = json.loads(
            run(
                kube
                + [
                    "-n",
                    route["namespace"],
                    "get",
                    "service",
                    route["service"],
                    "-o",
                    "json",
                ]
            )
        )
        ports = []
        for port in service["spec"]["ports"]:
            ports.append(port["port"])
        service_type = service["spec"].get("type", "ClusterIP")
        if service_type != "ClusterIP" or route["port"] not in ports:
            raise ValueError(
                f"{key} needs its expected ClusterIP service and port before exposure"
            )
        if key not in ("inference", "argocd", "grafana") and config["browser_auth"]["type"] == "oidc":
            secret = config["browser_auth"]["parameters"]["secretName"]
            run(
                kube + ["-n", route["namespace"], "get", "secret", secret, "-o", "name"]
            )
    # 4. Check the Cognito return addresses before exposing browser pages.
    browser_services = []
    for service in services:
        if service not in ("inference", "argocd", "grafana"):
            browser_services.append(service)
    if browser_services and config["browser_auth"]["type"] == "cognito":
        parameters = config["browser_auth"]["parameters"]
        # Filter client metadata: never capture or print the client secret.
        client = json.loads(
            run(
                aws
                + [
                    "cognito-idp",
                    "describe-user-pool-client",
                    "--user-pool-id",
                    parameters["userPoolARN"].split("/")[-1],
                    "--client-id",
                    parameters["userPoolClientID"],
                    "--query",
                    "UserPoolClient.{CallbackURLs:CallbackURLs,AllowedOAuthFlows:AllowedOAuthFlows}",
                ]
            )
        )
        for service in browser_services:
            callback_url = f"https://{config['hosts'][service]}/oauth2/idpresponse"
            if callback_url not in client.get("CallbackURLs", []):
                raise ValueError(
                    f"Cognito is missing this callback URL: {callback_url}"
                )
        if "code" not in client.get("AllowedOAuthFlows", []):
            raise ValueError(
                "Cognito client needs generated callback URLs and authorization-code flow"
            )
    return kube


def apply_bundle(config, services, directory, context):
    """Apply the routes only after every prerequisite check passes."""
    kube = preflight(config, services, context)
    print(
        command(kube + ["apply", "-f", str(Path(directory) / "external-dns.yaml")]),
        end="",
    )
    print(
        command(
            kube
            + [
                "-n",
                "external-dns",
                "rollout",
                "status",
                "deployment/external-dns",
                "--timeout=180s",
            ]
        ),
        end="",
    )
    if "argocd" in services:
        patch = json.dumps({"data": {"url": "https://" + config["hosts"]["argocd"]}})
        command(
            kube
            + [
                "-n",
                "argocd",
                "patch",
                "configmap",
                "argocd-cm",
                "--type=merge",
                "-p",
                patch,
            ]
        )
    if "litellm" in services:
        command(
            kube
            + [
                "-n",
                "gateway",
                "set",
                "env",
                "deployment/litellm",
                "PROXY_BASE_URL=https://" + config["hosts"]["litellm"],
            ]
        )
    if "grafana" in services:
        command(
            kube
            + [
                "-n",
                "monitoring",
                "set",
                "env",
                "deployment/monitoring-grafana",
                "GF_SERVER_DOMAIN=" + config["hosts"]["grafana"],
                "GF_SERVER_ROOT_URL=https://" + config["hosts"]["grafana"],
            ]
        )
    print(
        command(kube + ["apply", "-f", str(Path(directory) / "routes.yaml")]), end=""
    )
    print(
        "Routes applied. DNS, HTTPS, sign-in and inference still require live verification."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", help="Saved domain output; otherwise read local Terraform state"
    )
    parser.add_argument(
        "--services", nargs="+", choices=list(catalog()), default=list(catalog())
    )
    parser.add_argument("--output", default=str(ROOT / "k8s/generated/edge"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--context", help="Explicit kubectl context for this stack")
    parser.add_argument(
        "--host",
        choices=list(catalog()),
        help="Print one configured hostname without applying anything",
    )
    args = parser.parse_args()
    if args.apply and not args.context:
        parser.error("--apply requires --context")
    config = read_config(args.config)
    if args.host:
        validate(config)
        print(config["hosts"][args.host])
        return
    render_bundle(config, args.services, args.output)
    print(f"Rendered domain configuration into {args.output}")
    if args.apply:
        apply_bundle(config, args.services, args.output, args.context)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        print(f"Domain setup failed: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.strip(), file=sys.stderr)
        sys.exit(1)
