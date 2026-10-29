# Troubleshooting and Recovery

## Follow the failing request

Choose one exercise at a time in your test environment. Record a successful request before changing anything. Record the change, observed error, cause, correction and repeated test. Keep authentication enabled, preserve restricted application permissions and route model requests through the gateway.

Follow this order when a request fails: client configuration, DNS and TLS, ALB target health, LiteLLM authentication, database and Redis connectivity, vLLM readiness, then the model response.

```bash
kubectl -n platform-system get gateway astra-public
kubectl -n gateway get httproute astra-inference
kubectl -n gateway get pods -l app=litellm -o wide
kubectl -n gateway get endpointslices -l kubernetes.io/service-name=litellm
kubectl -n llm get pods -l app=vllm -o wide
kubectl -n llm get endpointslices -l kubernetes.io/service-name=vllm
```

**Expected result:** the Gateway has an address and is Programmed, the HTTPRoute is Accepted with ResolvedRefs, both Services have ready endpoints and both serving tiers have ready replicas. If a pod is not ready, inspect that exact pod with kubectl describe pod and its relevant container log. Save only the necessary redacted lines.

## Diagnose a rejected application key

Create a disposable key for astra and verify that it works. Revoke it through the authorized gateway administration process, then send the same request using that revoked key.

**Expected error:** HTTP 401 or 403. A network timeout is a different failure. Confirm that the gateway records an authorization rejection without recording the key itself.

Issue a replacement application key, store it through the approved secret process and update the test client. Run verify_endpoint.py again with the replacement key.

**Recovery:** the request returns HTTP 200 and an answer. Record the failed and successful statuses and revoke exercise-only keys afterward.

## Diagnose a denied tool request

Ask the Kubernetes assistant to list pods in kube-system. Its role allows the synthetic namespace, so this request must not return kube-system data.

```bash
kubectl auth can-i list pods -n kube-system --as=system:serviceaccount:k8s-assistant:k8s-assistant
kubectl auth can-i list pods -n synthetic --as=system:serviceaccount:k8s-assistant:k8s-assistant
```

Run these from an operator identity with impersonation permission. Expected results are no and yes. Inspect the assistant trace for the rejected tool operation, then repeat with the synthetic namespace.

**Recovery:** the permitted request completes and its answer uses the returned data. Correct the requested namespace rather than broadening the role to cluster-admin.

## Diagnose model integrity failures

Run the loader's corruption test from the repository. This deliberately supplies bytes that do not match the expected hash.

```bash
python -m unittest discover -s tests -p 'test_artifact_loader.py' -v
```

**Expected result:** the test passes because the loader rejects corrupt or oversized data and does not publish a completed model file. This is a local code test.

For the deployed exercise, use the separate staging deployment from Monitoring and Operations. Change only its expected manifest hash to an incorrect value. Inspect its verify-model init-container log. The init container must fail, and the staging pod must not become ready.

Restore the approved hash and recreate the staging pod with an empty model volume. Confirm its loader reports verified integrity before sending a staging test request. Keep live Service selectors unchanged during the exercise.

## Measure pod and store recovery

Run these exercises only against the disposable test platform. Send bounded authenticated probes during each exercise and record start time, failed requests, first successful recovery and final replica health. Complete one exercise before starting the next.

**Model pod loss:** choose one model pod from the current listing and set MODEL_POD to its exact name. Delete only that pod, then observe its replacement.

```bash
kubectl -n llm get pods -l app=vllm
kubectl -n llm delete pod "${MODEL_POD:?Set the exact model pod name}"
kubectl -n llm get pods -l app=vllm -w
```

Stop the watch with Ctrl+C after the replacement is ready. Repeat Platform Verification's release-identity check and authenticated request. The replacement must load the same approved release. Record interrupted streams separately.

**Gateway pod loss:** repeat the exercise with one exact gateway pod.

```bash
kubectl -n gateway get pods -l app=litellm
kubectl -n gateway delete pod "${GATEWAY_POD:?Set the exact gateway pod name}"
kubectl -n gateway get pods -l app=litellm -w
```

**Redis failover:** in ElastiCache, select the test replication group and use Test failover for its primary's node group. Watch events until the replica becomes primary. Confirm both gateways reconnect through the primary endpoint and the accepted shared-limit behavior is preserved.

**RDS failover:** in RDS, select the test Multi-AZ DB instance and use Reboot with failover. Watch its events and gateway database reconnection. Verify previously recorded synthetic application records and run a new authenticated request.

**Pass:** all four exercises have measured results, service recovers within the agreed target and the final request succeeds. A configured replica is not proof of tested recovery. Record any lost in-flight request and actual behavior during store unavailability.

## Restore a database and roll back a release

**Database restore:** create a known synthetic application record and record its identifier without the key. Take the agreed RDS snapshot. Restore that snapshot to a new private test instance with a different name and a security group restricted to the diagnostic client.

Connect a disposable gateway to the restored database. Confirm the expected application and usage records are present. Record snapshot time, recovery time and the comparison. Remove the disposable gateway and restore instance through Cleanup after verification.

**Release rollback:** keep the last approved model manifest, application image, prompt version and deployment configuration together. Deploy a deliberately failing candidate only to staging. Restore the complete prior combination, then repeat the authenticated request, both assistant tool-cycle checks and trace checks.

```bash
kubectl -n llm rollout history deployment/vllm
kubectl -n llm rollout status deployment/vllm --timeout=60m
```

Use the reviewed Git revert for an Argo CD-managed workload so the desired Git state also returns to the approved version. An emergency kubectl rollback must be reconciled with Git before synchronization resumes. Record the failed candidate, restored versions and passing checks.

## Rebuild one component from saved files

Choose a disposable staging component. Save its tested configuration and image digest, remove that component, then recreate it from the repository without copying settings from a running pod. Repeat the relevant Platform Verification check.

Record any missing step or configuration value, update the instructions and repeat the rebuild. Rebuilding a complete second platform is optional and needs its own operating-cost allowance.

## Maintain the platform operations runbook

Record the information needed to operate your deployed service: owner and support contact, approved release, measured capacity, AWS cost baseline, dashboard links, alert destination, key-rotation steps, backup/restore procedure and model-withdrawal procedure.

Attach the results from the recovery exercises above. Mark unfinished checks as pending. Keep the application team's connection instructions in Application Onboarding.
