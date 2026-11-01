import unittest
from unittest.mock import patch

from apps.assistant_tools import dispatch, tool_schema


class AssistantPermissionTests(unittest.TestCase):
    def test_forbidden_namespace_never_reaches_kubernetes(self):
        with patch("kubernetes.client.CoreV1Api") as api:
            with self.assertRaisesRegex(ValueError, "permissions"):
                dispatch("kubernetes", "list_pods", {"namespace": "kube-system"})
            api.assert_not_called()

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
        self.assertEqual([t["function"]["name"] for t in tool_schema("kubernetes")], ["list_pods"])


if __name__ == "__main__":
    unittest.main()
