#!/usr/bin/env bash
# Prepare the fresh CloudShell VPC checkout. Does not create AWS resources.
set -euo pipefail
test -f requirements.lock || { echo 'Run this from the starter repository root.' >&2; exit 1; }
test "$(uname -m)" = x86_64 || { echo 'This operator setup targets x86_64 Linux.' >&2; exit 1; }
mkdir -p .tools/bin
tools_dir="$PWD/.tools/bin"
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT

curl -fsSL https://dl.k8s.io/release/v1.35.10/bin/linux/amd64/kubectl -o "$work_dir/kubectl"
curl -fsSL https://dl.k8s.io/release/v1.35.10/bin/linux/amd64/kubectl.sha256 -o "$work_dir/kubectl.sha256"
printf '%s  %s\n' "$(cat "$work_dir/kubectl.sha256")" "$work_dir/kubectl" | sha256sum --check
install -m 0755 "$work_dir/kubectl" "$tools_dir/kubectl"

curl -fsSL https://get.helm.sh/helm-v4.3.1-linux-amd64.tar.gz -o "$work_dir/helm-v4.3.1-linux-amd64.tar.gz"
curl -fsSL https://get.helm.sh/helm-v4.3.1-linux-amd64.tar.gz.sha256sum -o "$work_dir/helm.sha256sum"
(cd "$work_dir" && sha256sum --check helm.sha256sum)
tar -xzf "$work_dir/helm-v4.3.1-linux-amd64.tar.gz" -C "$work_dir" linux-amd64/helm
install -m 0755 "$work_dir/linux-amd64/helm" "$tools_dir/helm"

if ! command -v uv >/dev/null; then
  python3 -m pip install --user uv==0.13.6
  export PATH="$HOME/.local/bin:$PATH"
fi
uv venv --python 3.13
uv pip sync --require-hashes --no-cache requirements.lock
printf '\nReady. Run these in this terminal:\nexport PATH="$PWD/.tools/bin:$PATH"\nsource .venv/bin/activate\n'
