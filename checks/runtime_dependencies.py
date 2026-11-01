"""Fail on dependency conflicts except the exact upstream NCCL override."""

import subprocess
import sys

# Upstream vLLM 0.32.0 Dockerfile overrides torch's NCCL pin for DeepEP.
# https://github.com/vllm-project/vllm/blob/v0.32.0/docker/Dockerfile
UPSTREAM_OVERRIDE = (
    'torch 2.13.0+cu130 has requirement nvidia-nccl-cu13==2.29.7; '
    'platform_system == "Linux", but you have nvidia-nccl-cu13 2.30.7.'
)


def check():
    result = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        capture_output=True, text=True, check=False,
    )
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    if result.returncode and result.stdout.strip().splitlines() != [UPSTREAM_OVERRIDE]:
        raise SystemExit("Unexpected runtime dependency conflict")
    if result.returncode:
        print("Exact upstream NCCL override recorded; GPU evaluation is still required.")


if __name__ == "__main__":
    check()
