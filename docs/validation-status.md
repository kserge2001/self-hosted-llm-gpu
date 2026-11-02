# Astra validation status

Updated November 2, 2026. This record separates live observations from untested changes.

## Live checks completed

- Provisioned the private EKS foundation, two CPU workers in separate zones, managed PostgreSQL and Redis, MLflow, S3, ECR and application access roles.
- Connected from a fresh private operator checkout and deployed the platform controllers, Argo CD, storage, monitoring and gateway.
- Downloaded and checked all 76 files for the pinned Qwen/Qwen3.8-27B-FP8 revision. The supplied CPU validation completed. Published exact S3 versions and verified the destination hashes.
- Loaded the model on one NVIDIA L40S using the repaired vLLM runtime. Model loading reported 27.94 GiB; total live GPU memory after startup was 36,498 MiB, about 35.64 GiB.
- `python first_request.py` returned a real Astra response over the authenticated HTTPS gateway at 19:57 UTC.
- The Kubernetes assistant called `list_pods` in the permitted synthetic namespace and returned its real empty result. The AWS assistant listed the four rehearsal EC2 instances after correcting their Project tags.
- Grafana's authenticated dashboard displayed GPU utilization, memory, temperature and power measurements from the live model worker.
- MLflow displayed both prompt versions and real assistant traces. The final export contains two experiments and three traces with no export errors. There are no model-evaluation runs because a separate GPU evaluation was not part of this rehearsal.
- Exported the records before teardown. At 20:34 UTC, AWS confirmed that EC2 instances, EKS, the VPC, ALB, NAT gateways, RDS, Redis, MLflow, Cognito and monitoring volumes were gone. No processing jobs remained. The final encrypted database snapshot is available, and the retained encryption key remains enabled. The separate operator and cost-backstop resources were also removed. Terraform contains only the explicitly retained resources.
- All eleven current lessons are published and checked in the site's rendered preview. The new diagram shows file preparation, GPU serving and a real response. The documented 34 Bash blocks pass syntax checks; no referenced Python scripts are missing. Syntax checking does not execute those commands.

## Remaining gaps

- **Two-zone GPU serving:** AWS capacity failures left the second model replica Pending. Only one model replica answered requests. No two-replica availability or failover pass is claimed.
- **Fresh student walkthrough:** The run required corrections while building. The latest guide and helper revisions have not all been replayed from a new student checkout. Private operator role and network setup must be made self-contained before calling the guide independently reproducible.
- **Manual Console guide:** Consolidating the duplicate engineering docs into the requested Console walkthrough remains open. [Current EKS documentation](https://docs.aws.amazon.com/eks/latest/userguide/view-kubernetes-resources.html) describes resource viewing in the Console; a click-only Kubernetes application deployment has not been demonstrated.
- **Starter release:** Classroom changes are pushed to `codex/astra-classroom-readiness`. Merge to `main` and a GitHub OIDC-driven release have not been verified.

## Repairs made during the rehearsal

The starter now supplies the CPU-only preparation path, exact-version lab publication, deployment configuration helpers, application request helper and MLflow export. Additional corrections cover server-side apply for monitoring definitions, GPU scheduling, explicit EC2 Project tags, Grafana hostname labels and cleanup retention of the encryption-key IAM dependency.

The tag change passes Terraform validation; the current workers were tagged directly for the successful assistant recheck. Automatic propagation on a new deployment has not been retested. The revised cleanup helper prepared and applied the reviewed teardown while retaining the specified storage, encryption keys and logs.

## Scope and evidence

The owner requested infrastructure, a real Astra answer, GPU metrics, MLflow information and model files. Separate model-quality evaluation, PR-building exercises, tuning and failure drills are outside this classroom rehearsal. MCP routing and LiteLLM guardrails are documentation topics; they were not configured or live-tested.

The runtime ran under the exact-image exception approved for this rehearsal. That exception is not a permanent company release approval. The four CPU service image scans were clean. Do not generalize the runtime exception to another image or deployment.

Detailed account-specific evidence stays outside Git under `evidence`: `astra-first-response-20261102.txt`, `grafana-gpu-live-20261102.json`, `mlflow-export-final-20261102.json`, screenshots, validation records and cleanup inventories. Model files and a copy of the live results are retained in the private S3 evidence/release buckets.

The last conservative planning estimate was $18 against the approved additional $20 ceiling. This is an estimate using AWS us-east-1 pricing and planned operating hours, not measured billing. Rehearsal-attributable billed cost is still unknown. Retained storage, snapshots, images, logs and keys can continue to incur charges.

## Cleanup after the live rehearsal

The model-evaluation question suite and separate GPU evaluation implementation were removed from the starter. Assistant deployment and trace startup no longer require an evaluation dataset. The supplied file-check helper replaces manual pipeline-operation steps in the lesson; the short reference note explains the checks. Infrastructure definitions are unchanged.

These revisions pass 125 local unit tests, the assistant HTTP/MLflow compatibility check and syntax checks for the current 32 Bash blocks across eleven lessons. The new helper, changed container definitions and final student sequence have not been deployed again. The earlier live evidence applies to the recorded rehearsal versions.
