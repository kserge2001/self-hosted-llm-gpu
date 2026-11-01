import copy
import json
import unittest
from pathlib import Path

from evaluate_model import run_case


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads(Path("evaluation/policy.json").read_text())
        self.cases = {case["id"]: case for case in json.loads(Path("evaluation/cases.json").read_text())["cases"]}

    @staticmethod
    def responder(messages, seconds=0.1):
        answers = iter(messages)
        return lambda *args, **kwargs: ({"choices": [{"message": next(answers)}]}, seconds)

    @staticmethod
    def tool(namespace="synthetic"):
        return {"role": "assistant", "content": None, "tool_calls": [{"id": "one", "type": "function",
                "function": {"name": "list_pods", "arguments": json.dumps({"namespace": namespace})}}]}

    def test_real_tool_cycle_required(self):
        case = self.cases["pending-pod"]
        fabricated = self.responder([{"content": "Pending because GPU is unavailable."}])
        self.assertFalse(run_case("unused", case, self.policy, fabricated)["passed"])
        valid = self.responder([self.tool(), {"content": "Pending because GPU is unavailable."}])
        self.assertTrue(run_case("unused", case, self.policy, valid)["passed"])

    def test_forbidden_namespace_is_rejected_at_dispatch(self):
        response = self.responder([self.tool("kube-system")])
        result = run_case("unused", self.cases["pending-pod"], self.policy, response)
        self.assertFalse(result["passed"])
        self.assertEqual(result["tools"], [])

    def test_injected_secret_fails_even_after_correct_tool(self):
        response = self.responder([self.tool(), {"content": "Pending. TRAINING_SECRET_731"}])
        self.assertFalse(run_case("unused", self.cases["tool-output-injection"], self.policy, response)["passed"])

    def test_json_output_compares_values(self):
        response = self.responder([{"content": '{"status":"ready","replicas":3}'}])
        self.assertFalse(run_case("unused", self.cases["json-output"], self.policy, response)["passed"])

    def test_repeated_tool_loop_is_bounded(self):
        result = run_case("unused", self.cases["pending-pod"], self.policy, self.responder([self.tool()] * 4))
        self.assertFalse(result["passed"])
        self.assertEqual(len(result["tools"]), 4)

    def test_slow_correct_answer_fails(self):
        response = self.responder([{"content": "5"}], self.policy["maximum_case_seconds"] + 1)
        self.assertFalse(run_case("unused", self.cases["plain-answer"], self.policy, response)["passed"])

    def test_service_error_is_failure_not_empty_success(self):
        def unavailable(*args, **kwargs):
            raise TimeoutError("synthetic unavailable service")
        self.assertFalse(run_case("unused", self.cases["plain-answer"], self.policy, unavailable)["passed"])


if __name__ == "__main__":
    unittest.main()
