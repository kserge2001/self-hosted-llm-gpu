import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

import configure_domains as domains


def fixture(domain="example.com"):
    labels = {
        "inference": "astra",
        "litellm": "litellm",
        "argocd": "argocd",
        "k8s_assistant": "k8sassistant",
        "aws_assistant": "awsassistant",
        "grafana": "grafana",
    }
    return {
        "domain_name": domain,
        "hosts": {key: value + "." + domain for key, value in labels.items()},
        "zone_id": "Z123456",
        "cluster_name": "astra-test",
        "cluster_endpoint": "https://test.eks.amazonaws.com",
        "acm_certificate_arn": "arn:aws:acm:us-east-1:123456789012:certificate/0123-abcd",
        "allowed_cidrs": ["203.0.113.10/32", "198.51.100.20/32"],
        "external_dns_role_arn": "arn:aws:iam::123456789012:role/astra-test-dns",
        "txt_owner_id": "astra-astra-test",
        "browser_auth": {
            "type": "cognito",
            "parameters": {
                "userPoolARN": "arn:aws:cognito-idp:us-east-1:123456789012:userpool/us-east-1_TEST",
                "userPoolClientID": "test-client",
                "userPoolDomain": "astra-test-0123",
            },
        },
    }


class DomainTests(unittest.TestCase):
    def test_litellm_root_opens_ui_without_redirecting_api_calls(self):
        resources = domains.build_routes(fixture(), ["litellm", "inference"])
        routes = {r["metadata"]["name"]: r for r in resources if r["kind"] == "HTTPRoute"}
        dashboard = routes["astra-litellm"]["spec"]["rules"]
        self.assertEqual(dashboard[0]["matches"][0]["path"], {"type": "Exact", "value": "/"})
        redirect = dashboard[0]["filters"][0]["requestRedirect"]
        self.assertEqual(redirect["path"]["replaceFullPath"], "/ui/")
        self.assertEqual(redirect["statusCode"], 302)
        self.assertIn("backendRefs", dashboard[1])
        self.assertNotIn("filters", routes["astra-inference"]["spec"]["rules"][0])

    def test_domain_change_reaches_all_routes_and_chart_values(self):
        for domain in ("example.com", "platform.example.org"):
            with self.subTest(domain=domain), tempfile.TemporaryDirectory() as temp:
                config = fixture(domain)
                resources = domains.render_bundle(config, list(domains.catalog()), temp)
                routes = [r for r in resources if r["kind"] == "HTTPRoute"]
                self.assertEqual({r["spec"]["hostnames"][0] for r in routes}, set(config["hosts"].values()))
                for filename in ("argocd-domain-values.yaml", "monitoring-domain-values.yaml", "endpoints.json"):
                    self.assertIn(domain, (Path(temp) / filename).read_text())
                controller = list(yaml.safe_load_all((Path(temp) / "external-dns.yaml").read_text()))[-1]
                args = controller["spec"]["template"]["spec"]["containers"][0]["args"]
                self.assertIn("--domain-filter=" + domain, args)
                self.assertIn("--zone-id-filter=Z123456", args)
                self.assertIn("--source=gateway-httproute", args)

    def test_custom_label_propagates_without_changing_other_services(self):
        config = fixture()
        config["hosts"]["k8s_assistant"] = "models.example.com"
        resources = domains.build_routes(config, ["k8s_assistant", "argocd"])
        routes = [r for r in resources if r["kind"] == "HTTPRoute"]
        self.assertEqual({r["spec"]["hostnames"][0] for r in routes}, {"models.example.com", "argocd.example.com"})

    def test_inference_uses_application_auth_and_never_exposes_admin_root(self):
        config = fixture()
        config["browser_auth"] = None
        resources = domains.build_routes(config, ["inference"])
        route = next(r for r in resources if r["kind"] == "HTTPRoute")
        self.assertFalse(any(r["kind"] == "ListenerRuleConfiguration" for r in resources))
        rule = route["spec"]["rules"][0]
        self.assertNotIn("filters", rule)
        self.assertEqual(rule["matches"][0]["path"], {"type": "PathPrefix", "value": "/v1"})
        self.assertEqual(rule["backendRefs"], [{"name": "litellm", "port": 4000}])

    def test_shared_signin_routes_require_cognito(self):
        resources = domains.build_routes(fixture(), list(domains.catalog()))
        authentication = {r["metadata"]["name"]: r for r in resources if r["kind"] == "ListenerRuleConfiguration"}
        for route in resources:
            if route["kind"] != "HTTPRoute" or route["metadata"]["name"] in ("astra-inference", "astra-argocd", "astra-grafana", "astra-litellm"):
                continue
            reference = route["spec"]["rules"][0]["filters"][0]["extensionRef"]["name"]
            protection = authentication[reference]
            self.assertEqual(protection["metadata"]["namespace"], route["metadata"]["namespace"])
            action = protection["spec"]["actions"][0]
            self.assertEqual(action["type"], "authenticate-cognito")
            self.assertEqual(action["authenticateCognitoConfig"]["onUnauthenticatedRequest"], "authenticate")

    def test_missing_browser_auth_stops_before_creating_files(self):
        config = fixture()
        config["browser_auth"] = None
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "output"
            with self.assertRaisesRegex(ValueError, "browser_auth"):
                domains.render_bundle(config, ["k8s_assistant"], output)
            self.assertFalse(output.exists())

    def test_rejects_duplicate_nested_or_foreign_hosts(self):
        for host in (
            "argocd.example.com",
            "one.two.example.com",
            "mlflow.other.example",
            "bad\n.example.com",
        ):
            config = fixture()
            config["hosts"]["k8s_assistant"] = host
            with self.subTest(host=host), self.assertRaises(ValueError):
                domains.validate(config)

    def test_unrestricted_or_ipv6_cidrs_rejected(self):
        for cidr in ("0.0.0.0/0", "::/0", "2001:db8::/32", "bad"):
            config = fixture()
            config["allowed_cidrs"] = [cidr]
            with self.subTest(cidr=cidr), self.assertRaises(ValueError):
                domains.validate(config)

    def test_no_public_vllm_route(self):
        with self.assertRaises(ValueError):
            domains.build_routes(fixture(), ["vllm"])

    def test_certificate_must_be_issued_and_cover_hosts(self):
        config = fixture()
        good = {"Status": "ISSUED", "DomainName": "*.example.com"}
        domains.assert_certificate(config, good, list(domains.catalog()))
        for bad in (
            {"Status": "PENDING_VALIDATION", "DomainName": "*.example.com"},
            {"Status": "ISSUED", "DomainName": "*.other.com"},
        ):
            with self.assertRaises(ValueError):
                domains.assert_certificate(config, bad, ["k8s_assistant"])

    def test_wrong_cluster_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            domains.assert_context(
                fixture(),
                {
                    "clusters": [
                        {
                            "cluster": {
                                "server": "https://existing-aip.eks.amazonaws.com"
                            }
                        }
                    ]
                },
            )

    def test_matching_cluster_cannot_disable_tls(self):
        with self.assertRaisesRegex(ValueError, "TLS"):
            domains.assert_context(
                fixture(),
                {
                    "clusters": [
                        {
                            "cluster": {
                                "server": fixture()["cluster_endpoint"],
                                "insecure-skip-tls-verify": True,
                            }
                        }
                    ]
                },
            )

    def test_existing_unowned_dns_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "already in use"):
            domains.assert_dns_ownership(
                fixture(), [{"Name": "astra.example.com.", "Type": "A"}], ["inference"]
            )

    def test_existing_owned_dns_is_idempotent(self):
        records = [
            {"Name": "astra.example.com.", "Type": "A"},
            {
                "Name": "_astra-a.astra.example.com.",
                "Type": "TXT",
                "ResourceRecords": [
                    {
                        "Value": '"heritage=external-dns,external-dns/owner=astra-astra-test,external-dns/resource=ingress/gateway/astra-inference"'
                    }
                ],
            },
        ]
        domains.assert_dns_ownership(fixture(), records, ["inference"])
        records[1]["ResourceRecords"][0][
            "Value"
        ] = '"external-dns/owner=astra-astra-test-other"'
        with self.assertRaises(ValueError):
            domains.assert_dns_ownership(fixture(), records, ["inference"])

    def test_failed_preflight_performs_no_mutation(self):
        with patch.object(
            domains, "preflight", side_effect=ValueError("collision")
        ), patch.object(domains, "command") as command:
            with self.assertRaises(ValueError):
                domains.apply_bundle(fixture(), ["inference"], Path("unused"), "test")
            command.assert_not_called()

    def test_argocd_keeps_https_backend(self):
        config = fixture()
        config["browser_auth"] = None
        resources = domains.build_routes(config, ["argocd"])
        target = next(r for r in resources if r["kind"] == "TargetGroupConfiguration")
        self.assertEqual(target["spec"]["defaultConfiguration"]["protocol"], "HTTPS")
        route = next(r for r in resources if r["kind"] == "HTTPRoute")
        self.assertNotIn("filters", route["spec"]["rules"][0])
        self.assertFalse(any(r["kind"] == "ListenerRuleConfiguration" for r in resources))

    def test_gateway_requires_https_allowlist_and_namespace_opt_in(self):
        config = fixture()
        resources = domains.build_routes(config, list(domains.catalog()))
        gateway = next(r for r in resources if r["kind"] == "Gateway")
        listener = gateway["spec"]["listeners"][0]
        self.assertEqual(listener["port"], 443)
        self.assertEqual(listener["protocol"], "HTTPS")
        self.assertEqual(listener["allowedRoutes"]["namespaces"]["from"], "Selector")
        load_balancer = next(r for r in resources if r["kind"] == "LoadBalancerConfiguration")
        self.assertEqual(load_balancer["spec"]["sourceRanges"], config["allowed_cidrs"])
        self.assertEqual(load_balancer["spec"]["listenerConfigurations"][0]["defaultCertificate"], config["acm_certificate_arn"])
        self.assertFalse(any(r["kind"] == "Ingress" for r in resources))

    def test_grafana_uses_its_own_login(self):
        config = fixture()
        config["browser_auth"] = None
        resources = domains.build_routes(config, ["grafana"])
        route = next(r for r in resources if r["kind"] == "HTTPRoute")
        self.assertNotIn("filters", route["spec"]["rules"][0])
        self.assertFalse(any(r["kind"] == "ListenerRuleConfiguration" for r in resources))

    def test_litellm_uses_its_own_login(self):
        config = fixture()
        config["browser_auth"] = None
        resources = domains.build_routes(config, ["litellm", "inference"])
        for route in resources:
            if route["kind"] == "HTTPRoute":
                for rule in route["spec"]["rules"]:
                    self.assertFalse(any(f["type"] == "ExtensionRef" for f in rule.get("filters", [])))
        self.assertFalse(any(r["kind"] == "ListenerRuleConfiguration" for r in resources))


if __name__ == "__main__":
    unittest.main()
