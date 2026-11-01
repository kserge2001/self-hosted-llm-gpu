# Validate, evaluate and publish an Astra model

The code in this guide is implemented but still awaiting its first complete AWS rehearsal. Do not interpret a local test or a published pipeline definition as a successful model evaluation. Keep GPUs off while building images and preparing configuration.

## Build before provisioning GPUs

The runtime preserves vLLM 0.32.0's CUDA, PyTorch and tracing stack while updating the fixable OS/Python dependencies. Its Dockerfile checks dependencies before removing unused installation tools. The exact upstream NCCL override is recorded; all other dependency conflicts fail the build.

```bash
docker build -f apps/Dockerfile.runtime -t astra-runtime:review .
docker build -f apps/Dockerfile.validation -t astra-validation:review .
docker build -f apps/Dockerfile.loader -t astra-loader:review .
docker build -f apps/Dockerfile.assistant -t astra-assistant:review .
python -m unittest discover -s tests -v
python checks/client_compatibility.py
python checks/assistant_compatibility.py
```

Push the reviewed images to your own ECR repositories and record their complete digest URIs. Scan the runtime by its ECR digest using the pinned Trivy scanner. Save the unmodified JSON report under the evidence bucket's `runtime/` prefix, recording its object version and SHA-256. A HIGH/CRITICAL finding blocks validation. The November 1 repaired image still has 385 kernel-header findings awaiting the [scoped exception decision](runtime-review.md); no exception is enabled in the release code.

Keep `gpu_enabled=false` in private foundation inputs until the runtime and release prerequisites are resolved. The foundation provisions separate validation, evaluation, pipeline and promotion roles. Processing uses private subnets; validation cannot approve a package, and promotion cannot change its approval status.

## Publish the definition without starting a GPU

Export the `model_pipeline` Terraform output to `evidence/pipeline-config.json`. Add three fields using your actual artifacts:

```json
{
  "validation_image": "YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/YOUR_REPOSITORY@sha256:YOUR_DIGEST",
  "runtime_image": "YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/YOUR_REPOSITORY@sha256:YOUR_DIGEST",
  "runtime_scan": {
    "uri": "s3://YOUR_EVIDENCE_BUCKET/runtime/scan.json",
    "version": "EXACT_S3_VERSION",
    "sha256": "EXACT_64_CHARACTER_SHA256"
  }
}
```

Merge these fields into the exported object; do not replace its IAM, network and bucket settings. Example strings intentionally fail validation.

```bash
python build_pipeline.py evidence/pipeline-config.json --output evidence/pipeline-definition.json
python deploy_pipeline.py evidence/pipeline-config.json --output evidence/pipeline-version.json
```

The second command creates or versions the definition. It does not start Processing. Record its returned pipeline version in the reviewed release request. Set the GitHub environment's `PIPELINE_NAME` variable to the foundation's `pipeline_name`, as well as its narrowly scoped `DEPLOY_ROLE_ARN`.

## Run the reviewed candidate

Complete [intake and malware scanning](model-intake-and-scanning.md) first. Use the exact candidate manifest URI, S3 version and SHA-256 in the release request. Follow the repository's PR and environment review process to start the pinned pipeline version.

Validation checks publisher identity and hashes, license label against the reviewed policy, exact-version malware events, runtime scan, file hashes and safetensors format. Only successful validation starts a GPU evaluation. Evaluation downloads the same object versions, starts vLLM offline on loopback, and runs the checked-in compatibility, tool, safety and latency cases. It writes individual results to S3 and a real evaluation run to MLflow.

Validation is capped at 30 minutes; GPU evaluation is capped at 60 minutes. vLLM initialization is additionally capped at 20 minutes and the process is terminated on completion or error. These bounds do not stop a separately deployed EKS GPU pool.

Inspect every case and the MLflow run. A successful evaluation registers a model package as **PendingManualApproval**. A failed result must not register or publish a release. The evaluation dataset is a small classroom regression suite; its pass result is not a production safety or capacity certification.

## Approve and publish

An authorized reviewer checks the actual results and approves the exact package in SageMaker Model Registry. Then assume the foundation's promotion role and run:

```bash
python promote_release.py --package-arn "$MODEL_PACKAGE_ARN" \
  --package-group "$MODEL_PACKAGE_GROUP" \
  --evidence-bucket "$EVIDENCE_BUCKET" \
  --quarantine-bucket "$QUARANTINE_BUCKET" \
  --release-bucket "$RELEASE_BUCKET"
```

Promotion re-reads current registry approval, rejects expired or mismatched evidence, copies exact object versions, and verifies every copied file. It writes `releases/RELEASE_ID/release-manifest.json` last and refuses to overwrite a completed manifest. Save the returned URI, version and SHA-256 together. The serving loader reads only those pinned versions from the release bucket.

Continue with [assistant and model deployment](serving-deployment.md), then perform the [classroom acceptance walkthrough](acceptance-checks.md) and [cleanup](cleanup.md). Keep the live verification record open until those steps have passed.
