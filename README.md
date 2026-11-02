# Astra platform starter

Build CareCart's internal inference service on AWS: a model on private EKS GPUs, a shared LiteLLM gateway, assistants, and observability.

Follow the [Astra capstone in Kodelumi](https://kodelumi.com/w/49_OMkQYNp9zuC57). The cleaned starter is on [`codex/astra-classroom-readiness`](https://github.com/kserge2001/self-hosted-llm-gpu/tree/codex/astra-classroom-readiness), pending merge into `main`.

## Build sequence

1. Prepare the code, pinned model metadata, and container images.
2. Create the AWS foundation with serving GPUs disabled.
3. Connect to the private cluster and bootstrap the shared tools.
4. Download the model and use the supplied file checks to publish it to S3.
5. Enable GPU workers, deploy Astra and LiteLLM, then send a request and confirm Astra responds.
6. Connect the supplied assistants and inspect Grafana, MLflow, and the model files in S3.
7. Export evidence and clean up the classroom infrastructure.

The design has two complete model replicas and two gateway replicas across two Availability Zones. Each model replica loads the full model on its own GPU. Use the first deployment's measurements to inform later improvements.

## What is included

- `infra/`: the Terraform foundation, private networking, and service permissions.
- `k8s/` and `argocd/`: model serving, gateway, assistants, and monitoring configuration.
- `apps/`: container definitions and application code.
- `assets/architecture/`: the foundation diagram and its editable source.
- `examples/astra_request.py`: a short application request through the gateway.
- Root Python helpers: model download and file preparation, configuration, deployment, access, and cleanup.
- `.github/workflows/`, `checks/`, and `tests/`: supplied automation and software checks.

The model preparation checks cover source and revision, license, file integrity and format, malware, and the server image scan. Students do not build a model evaluation suite or PR approval process. The course explains the supplied pipeline with a diagram and a brief checks note. The optional GitHub model-preparation workflow runs only when manually started; pushing this repository does not launch an AWS job.

MCP routing and guardrails are explained as LiteLLM capabilities. They are not configured features of this deployment. MLflow remains for prompts and request traces.

## Using this starter

Use your own repository, AWS account, domain, certificate, and authorized connection to the private cluster. The course assumes AWS credentials, AWS CLI, Python, uv, VS Code, and the earlier LLM Ops prerequisites. Shell examples use Bash.

Keep Terraform state in the same local `infra` directory through cleanup. State, saved plans, generated secrets, and private account inputs stay out of Git; `.terraform.lock.hcl` stays in version control.

Kodelumi is the student build guide. Duplicate engineering guides have been removed from this starter. The separate Console-only walkthrough is still pending.

## Validation status

The November 2, 2026 rehearsal returned an Astra response over HTTPS. Both assistants called their infrastructure tools, Grafana displayed GPU measurements, MLflow recorded prompts and traces, and the loader verified the 76 model files.

That run used one GPU because AWS could not allocate the second-zone GPU. Two-zone serving and an independent walkthrough of every revised student command remain unverified. The latest model-preparation and repository cleanup changes have local checks only; they have not been redeployed in AWS.

The rehearsal infrastructure was removed. Its service URLs are no longer live. Retained model files, images, logs, snapshots, and encryption keys may still incur charges.

Maintainers can run the supplied software checks locally:

```bash
python -m unittest discover -s tests -v
python checks/client_compatibility.py
python checks/assistant_compatibility.py
terraform -chdir=infra init -backend=false -lockfile=readonly
terraform -chdir=infra fmt -check
terraform -chdir=infra validate
```

These checks do not create AWS resources or prove that a deployed model responds.
