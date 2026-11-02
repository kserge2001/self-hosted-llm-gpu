# Astra platform starter

Build CareCart's first internal inference platform on AWS: private EKS GPU serving, a shared LiteLLM gateway, application access and observability.

Follow the [Astra capstone in Kodelumi](https://kodelumi.com/w/49_OMkQYNp9zuC57). The classroom implementation is on `codex/astra-classroom-readiness`; it has not been merged into `main`.

## Build sequence

1. Prepare the code, pinned model metadata and container images locally.
2. Create the AWS foundation with serving GPUs disabled.
3. Connect to the private cluster and bootstrap the shared tools.
4. Use the supplied model download, file-check and publication workflow.
5. Enable GPU workers, deploy Astra and LiteLLM, and make a real request.
6. Connect the supplied assistants and inspect Grafana, MLflow and the model files in S3.
7. Export evidence and remove the disposable classroom infrastructure.

The design uses two complete model replicas and two gateways across two Availability Zones. Each model replica loads the full model on its own GPU. Keep this design while using observed requests and GPU measurements to guide later improvements.

This is an infrastructure capstone. Students do not build PR approval systems or repeat model-quality, PII or OWASP evaluation exercises. The supplied repository retains broader evaluation code for separate use; it is not the required classroom path. MCP routing and guardrails are explained as LiteLLM capabilities, not configured features of this deployment.

## Verified rehearsal, November 2, 2026

A real HTTPS request returned an Astra answer. Both assistant applications made real infrastructure tool calls. Grafana displayed live L40S measurements, MLflow recorded prompt versions and request traces, and the serving loader verified the 76 model files.

One GPU replica served these requests. AWS could not allocate the second-zone GPU, so two-zone serving is still unverified. The build also required repairs during the rehearsal. A successful response does not mean that a fresh student can yet follow every revised command without assistance. See [the exact validation status](docs/validation-status.md).

The rehearsal's compute and networking are removed, including the MLflow tracking server. Its application URLs are no longer live. Retained model files, container images, logs, snapshots and encryption keys can continue to incur charges.

## Working conventions

Use your own repository, AWS account, domain, certificate and authorized private EKS connection. The course assumes the AWS CLI, Python, uv, VS Code and earlier LLM Ops prerequisites are already available. Shell examples use Bash.

Keep Terraform state in the same local `infra` directory through cleanup. State, saved plans, generated secrets and private account inputs must stay out of Git. Keep `.terraform.lock.hcl` in version control.

```bash
python -m unittest discover -s tests -v
terraform -chdir=infra init -backend=false -lockfile=readonly
terraform -chdir=infra fmt -check
terraform -chdir=infra validate
```

Local tests do not create AWS resources or prove live inference. The course is the student build guide; the existing files under `docs` still contain engineering references awaiting the requested consolidation into a separate manual Console guide.
