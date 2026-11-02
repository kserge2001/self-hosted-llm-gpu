"""Verify the supplied application example using a local HTTP fixture."""

import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx2
from openai import AuthenticationError, OpenAI


class OnboardingExampleTests(unittest.TestCase):
    def run_example(self, handler):
        code = Path("examples/astra_request.py").read_text(encoding="utf-8")
        code = code.replace("YOUR_ASTRA_HOST", "astra.example.com")

        def make_client(**settings):
            transport = httpx2.MockTransport(handler)
            return OpenAI(http_client=httpx2.Client(transport=transport), **settings)

        output = io.StringIO()
        with (
            patch("openai.OpenAI", side_effect=make_client),
            patch("getpass.getpass", return_value="synthetic-application-key"),
            contextlib.redirect_stdout(output),
        ):
            exec(compile(code, "onboarding-example", "exec"), {})
        return output.getvalue()

    def test_authenticated_chat_completion(self):
        def endpoint(request):
            self.assertEqual(
                str(request.url), "https://astra.example.com/v1/chat/completions"
            )
            self.assertEqual(
                request.headers["authorization"], "Bearer synthetic-application-key"
            )
            self.assertEqual(json.loads(request.content)["model"], "astra")
            return httpx2.Response(
                200,
                json={
                    "id": "test-answer",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "astra",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": "Synthetic answer.",
                            },
                        }
                    ],
                },
            )

        self.assertEqual(self.run_example(endpoint), "Synthetic answer.\n")

    def test_invalid_key_is_rejected(self):
        def endpoint(request):
            return httpx2.Response(
                401,
                json={
                    "error": {
                        "message": "Invalid test key",
                        "type": "authentication_error",
                    }
                },
            )

        with self.assertRaises(AuthenticationError):
            self.run_example(endpoint)
