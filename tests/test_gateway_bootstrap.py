"""Check that retries preserve credentials and database TLS stays verified."""
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from apps.initialize_gateway import main


class GatewayBootstrapTests(unittest.TestCase):
    def test_retry_reuses_credentials_after_database_failure(self):
        stored = {
            "admin": json.dumps({"username": "admin", "password": "test-only"}),
            "redis": "test-redis",
        }
        client = MagicMock()
        client.describe_secret.side_effect = lambda SecretId: {
            "VersionIdsToStages": {"version": ["AWSCURRENT"]} if SecretId in stored else {}
        }
        client.get_secret_value.side_effect = lambda SecretId: {"SecretString": stored[SecretId]}
        client.put_secret_value.side_effect = lambda SecretId, SecretString: stored.update({SecretId: SecretString})
        environment = {
            "MODEL_SECRET_ARN": "model", "GATEWAY_SECRET_ARN": "gateway",
            "POSTGRES_ADMIN_SECRET_ARN": "admin", "REDIS_SECRET_ARN": "redis",
            "POSTGRES_HOST": "db.example.com", "REDIS_HOST": "redis.example.com",
            "LITELLM_HOST": "litellm.example.com",
        }
        with patch.dict(os.environ, environment), patch("apps.initialize_gateway.boto3.client", return_value=client):
            with patch("apps.initialize_gateway.psycopg.connect", side_effect=ConnectionError):
                with self.assertRaises(ConnectionError):
                    main()
            saved = stored.copy()
            with patch("apps.initialize_gateway.psycopg.connect") as connect:
                main()
                self.assertEqual(connect.call_args.kwargs["sslmode"], "verify-full")
                self.assertEqual(connect.call_args.kwargs["sslrootcert"], "/app/rds-ca.pem")
            self.assertEqual(stored, saved)
            self.assertEqual(client.put_secret_value.call_count, 2)
            settings = json.loads(stored["gateway"])
            self.assertIn("sslaccept=strict", settings["DATABASE_URL"])
            self.assertIn("sslcert=/certs/rds-ca.pem", settings["DATABASE_URL"])
            self.assertTrue(settings["REDIS_URL"].startswith("rediss://"))
            self.assertEqual(settings["VLLM_API_KEY"], json.loads(stored["model"])["api-key"])
