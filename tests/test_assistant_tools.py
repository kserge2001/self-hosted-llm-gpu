import unittest
from types import SimpleNamespace as Record
from unittest.mock import patch

from apps.assistant_tools import dispatch, tool_schema


class AssistantPermissionTests(unittest.TestCase):
    def test_forbidden_namespace_never_reaches_kubernetes(self):
        with patch("kubernetes.client.CoreV1Api") as api, patch("kubernetes.client.AppsV1Api") as apps:
            for name in ("list_pods", "describe_deployment", "recent_events"):
                args = {"namespace": "kube-system"}
                if name == "describe_deployment":
                    args["name"] = "example"
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, "permissions"):
                    dispatch("kubernetes", name, args)
            api.assert_not_called()
            apps.assert_not_called()

    def test_deployment_result_contains_only_health_summary(self):
        with patch("kubernetes.client.AppsV1Api") as api:
            api.return_value.read_namespaced_deployment.return_value = Record(
                metadata=Record(name="healthy", generation=3), spec=Record(replicas=2),
                status=Record(observed_generation=3, ready_replicas=2, available_replicas=2, conditions=[]))
            result = dispatch("kubernetes", "describe_deployment", {"namespace": "synthetic", "name": "healthy"})
            self.assertEqual(result["ready_replicas"], 2)
            self.assertEqual(result["observed_generation"], 3)
            api.return_value.read_namespaced_deployment.assert_called_once_with("healthy", "synthetic", _request_timeout=10)

    def test_invalid_deployment_names_never_reach_sdk(self):
        with patch("kubernetes.client.AppsV1Api") as api:
            for value in ("../kube-system", "Bad Name", "", 123, "x" * 254):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    dispatch("kubernetes", "describe_deployment", {"namespace": "synthetic", "name": value})
            api.assert_not_called()

    def test_events_are_bounded_and_truncation_is_reported(self):
        event = Record(last_timestamp=None, event_time=None, metadata=Record(creation_timestamp=None),
                       involved_object=Record(name="pending", kind="Pod"), type="Warning",
                       reason="FailedScheduling", message="x" * 400, count=1)
        with patch("kubernetes.client.CoreV1Api") as api:
            api.return_value.list_namespaced_event.return_value = Record(items=[event] * 100, metadata=Record(_continue="next"))
            result = dispatch("kubernetes", "recent_events", {"namespace": "synthetic"})
            self.assertTrue(result["truncated"])
            self.assertEqual(len(result["events"]), 20)
            self.assertEqual(len(result["events"][0]["message"]), 300)
            self.assertEqual(api.return_value.list_namespaced_event.call_count, 3)

    def test_cross_assistant_tools_rejected(self):
        for kind, name, args in [("aws", "list_pods", {"namespace": "synthetic"}),
                                 ("kubernetes", "list_instances", {}),
                                 ("aws", "terminate_instances", {})]:
            with self.subTest(kind=kind, name=name), self.assertRaises(ValueError):
                dispatch(kind, name, args)

    def test_extra_aws_arguments_rejected_before_sdk(self):
        with patch("apps.aws_tools.list_instances") as call:
            with self.assertRaises(ValueError):
                dispatch("aws", "list_instances", {"region": "us-west-2"})
            call.assert_not_called()

    def test_only_approved_tools_are_offered(self):
        self.assertEqual([t["function"]["name"] for t in tool_schema("aws")], ["list_instances"])
        self.assertEqual([t["function"]["name"] for t in tool_schema("kubernetes")],
                         ["list_pods", "describe_deployment", "recent_events"])


if __name__ == "__main__":
    unittest.main()
