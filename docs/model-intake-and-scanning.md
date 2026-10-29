# Model intake and scanning

## A. Prepare the candidate

Use the astra-candidate.json produced by Model and Capacity. Review the publisher, pinned revision and license before downloading. This job accepts the recorded safetensors weights and a short list of configuration and tokenizer files. It verifies publisher hashes and uploads into quarantine. It does not approve or serve a model.

Apply the foundation first. The model_scanning Terraform output must show ACTIVE. Keep the Python environment active and use the private cluster connection established in AWS Foundation.

## B. Build the intake image

The image contains quarantine_intake.py and its dependencies. Use your own ECR repository from the images Terraform output. The example uses its assistant repository for this small utility image.

```bash
export INTAKE_REPOSITORY=$(terraform -chdir=infra output -json images | python -c 'import json,sys; print(json.load(sys.stdin)["assistant"])')
export ECR_REGISTRY=${INTAKE_REPOSITORY%%/*}
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin "$ECR_REGISTRY"
docker build -f apps/Dockerfile.model-intake -t "$INTAKE_REPOSITORY:model-intake" .
docker push "$INTAKE_REPOSITORY:model-intake"
export INTAKE_DIGEST=$(aws ecr describe-images --region us-east-1 \
  --repository-name "${INTAKE_REPOSITORY#*/}" --image-ids imageTag=model-intake \
  --query 'imageDetails[0].imageDigest' --output text)
export INTAKE_IMAGE="$INTAKE_REPOSITORY@$INTAKE_DIGEST"
```

## C. Run the intake job

Choose a new release ID for the attempt. The job keeps only one downloaded file on disk at a time. Its role can write to quarantine, but cannot publish a release or modify the scan-event log.

```bash
export RELEASE_ID=astra-candidate-001
export INTAKE_JOB_NAME="intake-$RELEASE_ID"
export CANDIDATE_CONFIGMAP="candidate-$RELEASE_ID"
export INTAKE_ROLE_ARN=$(terraform -chdir=infra output -json model_scanning | python -c 'import json,sys; print(json.load(sys.stdin)["intake_role_arn"])')
export QUARANTINE_BUCKET=$(terraform -chdir=infra output -json buckets | python -c 'import json,sys; print(json.load(sys.stdin)["quarantine"])')
python render_manifest.py k8s/model-intake.yaml k8s/generated/model-intake.yaml
kubectl create namespace model-intake --dry-run=client -o yaml | kubectl apply -f -
kubectl -n model-intake create configmap "$CANDIDATE_CONFIGMAP" --from-file=astra-candidate.json
kubectl apply -f k8s/generated/model-intake.yaml
kubectl -n model-intake logs -f "job/$INTAKE_JOB_NAME"
```

The last log line contains the manifest URI, S3 version and SHA-256 fingerprint. Keep all three together. A complete manifest is written only after every selected file is verified and uploaded. Check the Job is Complete. If it fails, read the error, correct the cause and use a new attempt ID. A partial upload is not a release.

## D. Verify the scan results

GuardDuty scans uploads and sends results to the dedicated CloudWatch log group. scan_gate.py matches the bucket, object path and exact version. A missing, skipped, failed or threat-positive scan stops the check. An editable S3 tag is not accepted as evidence.

Use the manifest values from the completed job and the plan ARN and log group from this stack. Do not substitute the manifest of another attempt.

```bash
export SCAN_LOG_GROUP=$(terraform -chdir=infra output -json model_scanning | python -c 'import json,sys; print(json.load(sys.stdin)["event_log_group"])')
export MALWARE_PLAN_ARN=$(terraform -chdir=infra output -json model_scanning | python -c 'import json,sys; print(json.load(sys.stdin)["protection_plan_arn"])')
python scan_gate.py --manifest-uri "$CANDIDATE_MANIFEST_URI" \
  --version "$CANDIDATE_MANIFEST_VERSION" --sha256 "$CANDIDATE_MANIFEST_SHA256" \
  --log-group "$SCAN_LOG_GROUP" --plan-arn "$MALWARE_PLAN_ARN"
```

Expected result: malware is PASS and every file has a matching event ID. Scans can finish after the upload. If a result is missing, check GuardDuty and the event delivery before rerunning the check. Never change a missing result to PASS.

The candidate must still pass runtime vulnerability scanning, format and compatibility checks, evaluation and release approval. The full SageMaker evaluation and promotion pipeline remains under implementation; completing this intake step does not mean Astra can answer requests.
