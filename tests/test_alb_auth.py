import os
import time
import unittest
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException

from apps.alb_auth import authenticated_user


class LoadBalancerIdentityTests(unittest.TestCase):
    def setUp(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.settings = {
            "EXPECTED_ALB_ARN": "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/astra/1234",
            "COGNITO_CLIENT_ID": "approved-client",
        }
        self.headers = {
            "kid": "12345678-1234-1234-1234-123456789012",
            "signer": self.settings["EXPECTED_ALB_ARN"],
            "client": self.settings["COGNITO_CLIENT_ID"],
            "exp": int(time.time()) + 300,
        }

    def token(self, **changes):
        return jwt.encode({"sub": "test-engineer"}, self.key, algorithm="ES256", headers=self.headers | changes)

    def check(self, token):
        with patch.dict(os.environ, self.settings), patch("apps.alb_auth.public_key", return_value=self.key.public_key()):
            return authenticated_user(token)

    def test_valid_signed_identity(self):
        self.assertEqual(self.check(self.token()), "test-engineer")

    def test_missing_foreign_or_expired_identity_is_rejected(self):
        invalid = ["", self.token(signer="another-load-balancer"), self.token(client="another-client"), self.token(exp=1)]
        for token in invalid:
            with self.subTest(token_kind=bool(token)), self.assertRaises(HTTPException) as failure:
                self.check(token)
            self.assertEqual(failure.exception.status_code, 401)

    def test_forged_signature_is_rejected(self):
        other_key = ec.generate_private_key(ec.SECP256R1())
        token = jwt.encode({"sub": "test-engineer"}, other_key, algorithm="ES256", headers=self.headers)
        with self.assertRaises(HTTPException):
            self.check(token)


if __name__ == "__main__":
    unittest.main()
