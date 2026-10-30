# Optional engineering checks

## Prepare the verification record

Run these checks after deploying the relevant components. Use your deployed names and the release record from the build. Keep an item unchecked until its expected result is observed. For each result, record the date, release ID, command or UI action, PASS or FAIL, and an evidence file or trace ID.

Use the [starter repository](https://github.com/kserge2001/self-hosted-llm-gpu). Save permitted output locally under evidence; that directory is excluded from Git. Use synthetic requests and remove secrets from screenshots and logs.

```bash
mkdir -p evidence
python -m unittest discover -s tests -v
```

**Expected result:** the local tests pass. This checks the scripts; it does not prove the deployed platform passes the checks below.

## Verify the endpoint, replicas and access

- [ ] **1. Make an authenticated request from local code.** The SDK example is in Application Onboarding. For this optional command-line check, set ASTRA_HOST to your API hostname; the script asks for the application key without displaying it. Run:

```bash
python verify_endpoint.py --expect allowed
kubectl -n platform-system get gateway astra-public -o yaml
kubectl -n gateway get httproute astra-inference -o yaml
```

**Pass:** the script reports PASS and HTTP 200 after receiving an answer. The Gateway is Programmed with an ALB address; the HTTPRoute is Accepted with ResolvedRefs. In the EC2 load-balancer console, verify the internet-facing scheme, HTTPS 443, the intended ACM certificate, healthy targets and an inbound allowlist restricted to approved source addresses. From a network outside that allowlist, the connection must fail. Save the response status and redacted listener/security-group evidence.

- [ ] **2. Verify the two vLLM replicas and their release.**

```bash
kubectl -n llm rollout status deployment/vllm --timeout=60s
kubectl -n llm get pods -l app=vllm -o custom-columns='POD:.metadata.name,READY:.status.containerStatuses[*].ready,NODE:.spec.nodeName,RELEASE:.metadata.labels.release,IMAGE:.status.containerStatuses[*].imageID'
kubectl get nodes -L topology.kubernetes.io/zone
for pod in $(kubectl -n llm get pods -l app=vllm -o name); do
  kubectl -n llm exec "$pod" -c vllm -- cat /models/astra/release-identity.json
  kubectl -n llm logs "$pod" -c verify-model
done
```

**Pass:** both replicas are ready, their nodes map to different zones, both release identities and manifest hashes match the approved record, and both loader logs report verified integrity. Match the runtime image digest too. A release label alone is insufficient.

- [ ] **3. Verify shared Redis and PostgreSQL.**

```bash
kubectl -n gateway get pods -l app=litellm -o wide
kubectl -n gateway get deployment litellm -o jsonpath='{.spec.template.spec.containers[0].envFrom}'
kubectl -n gateway get service litellm
kubectl -n gateway get endpointslices -l kubernetes.io/service-name=litellm
```

**Pass:** both ready pods use litellm-env and the ClusterIP Service has both endpoints. In the authorized secret manager, compare only the connection hostnames: Redis uses the managed primary endpoint and PostgreSQL uses the RDS endpoint. Do not print the connection strings. Send requests through each gateway using an approved diagnostic client and the same test application key. Confirm one shared usage record and the configured shared rate limit. Save pod names, redacted hostnames and the usage result.

- [ ] **4. Reject missing, revoked and unauthorized keys.** Run a missing-key test:

```bash
python verify_endpoint.py --expect denied
```

Create two disposable application keys: one allowed to use astra and one without astra permission. Confirm the allowed key works, revoke it, then test it again through the same HTTPS address. Load the revoked and unauthorized keys into REVOKED_KEY and UNAUTHORIZED_KEY using hidden prompts as in Application Onboarding.

```bash
python verify_endpoint.py --expect denied --key-env REVOKED_KEY
python verify_endpoint.py --expect denied --key-env UNAUTHORIZED_KEY
unset REVOKED_KEY UNAUTHORIZED_KEY
```

**Pass:** each denial reports PASS with HTTP 401 or 403 and an API error. A timeout, certificate error, 429 or 5xx is not evidence that key authorization works. Keep the valid-key baseline and denied statuses.

- [ ] **5. Prevent direct application access to vLLM.** From the Kubernetes assistant pod, use its Python interpreter to try the backend health URL. Set APP_POD to that pod's name:

```bash
kubectl -n k8s-assistant exec "$APP_POD" -- python -c 'import urllib.request; urllib.request.urlopen("http://vllm.llm.svc.cluster.local:8000/health", timeout=5)'
kubectl -n llm get networkpolicy
```

**Pass:** the connection is blocked by the applied network policy. Any HTTP response, including 401, means the network path exists and needs investigation. Repeat an allowed gateway request to distinguish an isolation rule from a broken model service. A missing Python interpreter is not a passing test.

- [ ] **6. Verify the serving identity's boundaries.** Use a disposable diagnostic pod with the vllm service account and the approved AWS CLI image. Read a known synthetic object from the release bucket by version, then attempt a known synthetic quarantine object. Attempt a write only to the designated permission-test prefix in the evidence bucket, never to an existing report.

**Pass:** the release read succeeds; the quarantine read and evidence write return AccessDenied. Save the caller identity and error codes with account details redacted. If the test write succeeds, remove that test object, correct the role and repeat. An IAM policy document or simulator result alone does not complete this live check.

## Verify the model release controls

- [ ] **7. Verify scanning and evaluation before promotion.**

```bash
aws sagemaker list-pipeline-execution-steps --region us-east-1 \
  --pipeline-execution-arn "$PIPELINE_EXECUTION_ARN"
aws sagemaker describe-model-package --region us-east-1 \
  --model-package-name "$MODEL_PACKAGE_ARN" \
  --query '{Approval:ModelApprovalStatus,Metadata:CustomerMetadataProperties}'
```

**Pass:** the exact pinned Hugging Face revision is linked to per-object scan evidence, successful validation/evaluation steps, an MLflow evaluation run and the reviewed model package. Compare their hashes and timestamps with the promoted release. A successful GitHub trigger alone does not pass this item.

- [ ] **8. Block failed or unapproved candidates.**

```bash
python -m unittest discover -s tests -p 'test_release_gate.py' -v
```

Then run the isolated rejection exercises from Model Release Pipeline: an incomplete scan result, a failed evaluation and a package left PendingManualApproval. Use synthetic evidence in the dedicated test workflow; never manufacture a successful malware scan.

**Pass:** all three attempts stop before publication, no complete release-manifest.json is written for those candidate IDs, and the previously approved serving release still answers. Save each execution ARN and the rejected reason. Local unit tests alone do not complete this item.

- [ ] **9. Verify the release manifest.** Retrieve the exact manifest version recorded by promotion:

```bash
aws s3api get-object --region us-east-1 \
  --bucket "$RELEASE_BUCKET" --key "$MANIFEST_KEY" \
  --version-id "$MANIFEST_VERSION" evidence/release-manifest.json
sha256sum evidence/release-manifest.json
python -m json.tool evidence/release-manifest.json
```

**Pass:** the file hash matches MANIFEST_SHA256. Inspect the publisher/repository, full revision, release ID, runtime image digest, object keys, object versions, sizes and hashes. Compare them with the loader identities from check 2 and the approval evidence from check 7. Save the manifest and comparison.

## Verify applications and MLflow

- [ ] **10. Complete a Kubernetes assistant tool cycle.** Ask the application to explain a synthetic Pending pod in its permitted namespace. Inspect its response and MLflow trace.

**Pass:** the trace shows an Astra model call, the approved Kubernetes tool and arguments, the tool result and a final answer consistent with that result. Save the request and trace IDs. A direct cURL model answer does not prove the assistant's tool loop works.

- [ ] **11. Complete an AWS assistant tool cycle.** Ask the AWS assistant to list the state of Astra-tagged EC2 instances. Inspect the tool result and trace, then compare the instance state with EC2.

**Pass:** the assistant uses list_instances with its own read-only role and application key. The answer matches returned data, and LiteLLM attributes the usage to the AWS assistant rather than the Kubernetes assistant. Save the trace ID and redacted usage evidence.

- [ ] **12. Enforce tool permissions outside the prompt.** Run the Kubernetes authorization checks from an operator identity allowed to impersonate this service account:

```bash
kubectl auth can-i list pods -n synthetic --as=system:serviceaccount:k8s-assistant:k8s-assistant
kubectl auth can-i list pods -n kube-system --as=system:serviceaccount:k8s-assistant:k8s-assistant
kubectl auth can-i delete pods -n synthetic --as=system:serviceaccount:k8s-assistant:k8s-assistant
```

**Pass:** results are yes, no and no. Also request the forbidden namespace through the actual assistant and confirm it cannot retrieve that data. Under the AWS assistant's identity, use EC2 terminate-instances with --dry-run against a disposable test instance. UnauthorizedOperation is the expected denial; DryRunOperation means the role has termination permission and fails the check. Never omit --dry-run. Save the denied results and correct any excessive permission.

- [ ] **13. Verify MLflow browser access.** Sign in to the AWS console with an approved identity. Open SageMaker AI > Studio > Applications > MLflow, then choose Open MLflow for the tracking server. Repeat with a test identity without MLflow permissions.

**Pass:** access requires sign-in, the approved AWS identity reaches the managed MLflow UI, and the unauthorized identity is denied. Save redacted screenshots. Do not save the temporary signed redirect URL.

- [ ] **14. Verify prompt versions.** Open the Prompt Registry in the managed MLflow UI. Open the prompt used by each assistant and compare its numeric version and content hash with the application's release record.

**Pass:** both the registered version and the application-linked version are visible and agree. Keep the version URI and redacted screenshot.

- [ ] **15. Verify real application traces.** Run one fresh request through each assistant and open the resulting traces.

**Pass:** each trace has the real model and tool spans, their timing and status, and the correct application/model release references. The earlier synthetic trace smoke test does not satisfy this check.

- [ ] **16. Inspect evaluation results and feedback.** Open the evaluation run linked to the release. Inspect its scores, individual case report, reviewer feedback and permitted artifacts using the intended reviewer identity.

**Pass:** the results are readable and linked to the actual candidate; a passing summary is supported by individual cases. Record the run ID and evidence locations. Leave the item incomplete if the selected managed MLflow version does not support a required feature.

- [ ] **17. Follow the release lineage.** Start from an assistant request and follow its trace to the application image, numeric prompt version, Astra release, tool-schema hash and evaluation dataset hash.

**Pass:** all five identities can be found and match the release record. Save their IDs and links. An unlinked artifact in a bucket does not establish lineage.

## Verify monitoring and recovery

- [ ] **18. Verify live monitoring.** Send a small number of synthetic requests. Open Grafana and inspect GPU utilization/memory, ready model and gateway replicas, queues, errors and response time. Open CloudWatch for EKS logs and the relevant AWS service metrics.

**Pass:** the charts contain current data for both GPU replicas and gateway pods, and request activity is visible. Check timestamps and scrape-target health; a static dashboard with no data does not pass. Save timestamped screenshots and a representative log event without prompt content.

- [ ] **19. Verify alert delivery.** Create a temporary test alert in the test environment that matches a known current metric. Route it through the configured notification path, then remove the test rule after it fires.

**Pass:** the alert reaches the intended operational destination with the correct service and severity, then resolves. Record its firing, receipt and resolution times. Use a designated test destination for the exercise.

- [ ] **20. Verify rollback.** Follow Troubleshooting and Recovery to deploy a deliberately failing candidate in staging. Restore the saved model, application and prompt combination.

**Pass:** the restored versions match the prior approved record, the authenticated request passes and both assistant regression tests pass. Save the failed rollout event, restored release identity and test results. A successful rollout command alone is insufficient.

- [ ] **21. Measure failure recovery.** Perform the four separate exercises in Troubleshooting and Recovery: one model pod loss, one gateway pod loss, Redis failover and RDS failover. Run a bounded request probe during each exercise.

**Pass:** each exercise records the injected failure time, failed/interrupted requests, recovery time and a successful final authenticated request. Compare recovery with the agreed target. Record streams that fail; do not claim they transfer to another replica.

- [ ] **22. Verify a database restore.** Restore the selected RDS snapshot to a new isolated private instance. Connect a disposable gateway to that restored database and compare the expected synthetic application records and usage rows.

**Pass:** the restored records agree with the snapshot's test baseline, the disposable gateway can read them, and live gateway configuration remains unchanged. Save the snapshot ID, restore ID and redacted comparison, then remove the disposable gateway and restored instance through Cleanup.

## Verify automation, recovery access and costs

- [ ] **23. Verify CI, GitOps and the OIDC boundary.** Submit a real model-release PR. Inspect the hosted checks, approved merge, environment approval and recorded SageMaker execution ARN in GitHub Actions. Inspect the deployed revision in Argo CD.

```bash
kubectl -n argocd get applications -o wide
```

**Pass:** the trusted GitHub-hosted job starts the intended pipeline version, and Argo CD reports the expected Git revision as Synced and Healthy. From a controlled test repository outside the OIDC trust, attempt the same role assumption without other AWS credentials. Expect AccessDenied from STS. Save both job results and the Argo CD revision. Do not weaken role trust for the negative test.

- [ ] **24. Verify recovery without CI.** Use the authorized operator session and saved Terraform state to reach the private EKS API. Inspect and recover the Argo CD deployment from the recorded configuration while no CI job is running.

```bash
kubectl -n argocd get deployments,pods
```

**Pass:** you can reach the cluster and restore the controller without a GitHub job. Argo CD returns to Healthy and Synced at the approved revision. Record the recovery steps. Do not destroy the cluster for this check.

- [ ] **25. Verify the recorded versions.**

```bash
terraform version
terraform -chdir=infra providers
helm list -A
kubectl -n llm get pods -l app=vllm -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.containerStatuses[*].imageID}{"\n"}{end}'
```

**Pass:** the release record includes the tested Terraform/Python versions, provider lock file, exact chart versions and deployed image digests. Compare recorded values with these results and the CI run. Save the comparison; a floating image tag is insufficient.

- [ ] **26. Review actual costs.** In AWS Cost Explorer, select the test dates and account, group by service and inspect the platform's compute, GPU, SageMaker, MLflow, database, cache, network and storage charges. Filter by Project tags where cost allocation tags have been activated. Review LiteLLM's application usage for the same period separately.

**Pass:** you can explain the AWS charges and the gateway's token-based accounting without treating them as the same bill. Record the date range, costs and any billing-data delay. Keep the review open until delayed charges are visible.
