"""Verify the signed identity sent by this platform's load balancer."""

import os
import re
import time
from functools import lru_cache
from urllib.request import urlopen

import jwt
from fastapi import HTTPException


@lru_cache(maxsize=8)
def public_key(key_id):
    # Only AWS's fixed regional key endpoint is allowed.
    if not re.fullmatch(r"[a-fA-F0-9-]{36}", key_id):
        raise ValueError("Invalid key identifier")
    url = "https://public-keys.auth.elb.us-east-1.amazonaws.com/" + key_id
    with urlopen(url, timeout=5) as response:
        return response.read(16384)


def authenticated_user(token):
    """Reject missing, forged, expired or foreign load-balancer identities."""
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "ES256":
            raise ValueError("Unexpected signing algorithm")
        if header.get("signer") != os.environ["EXPECTED_ALB_ARN"]:
            raise ValueError("Unexpected load balancer")
        if header.get("client") != os.environ["COGNITO_CLIENT_ID"]:
            raise ValueError("Unexpected sign-in client")
        claims = jwt.decode(token, public_key(header["kid"]), algorithms=["ES256"])
        # AWS places expiration in the signed JWT header, not the payload.
        if float(header["exp"]) <= time.time() or not claims.get("sub"):
            raise ValueError("Expired or missing identity")
        return claims["sub"]
    except (jwt.PyJWTError, ValueError, KeyError, TypeError, OSError):
        raise HTTPException(status_code=401, detail="Sign in through the platform address") from None
