# Validation status

Updated November 1, 2026. Classroom-readiness changes are prepared locally from e2e/astra commit 177b3f1. The test account's credentials, Terraform state and private configuration are not included. No new AWS compute was launched for this work.

## Local readiness work since teardown

- The current local suite has 109 passing tests. Terraform validation and its three mocked tests pass.
- The runtime image builds with repaired OS/Python dependencies, compatible tracing packages and only the exact upstream NCCL dependency override. Unused installation tools and their bundled dependencies are removed together.
- The October 30 repaired-image scan reports 386 HIGH/CRITICAL findings, all against linux-libc-dev 6.8.0-147.147. The fixable non-header findings are gone. Official Linux CVE records were retrieved for every remaining finding, and an inventory confirms the container contains no kernel binaries. One CVE also changes a UAPI header; its vulnerable conntrack implementation is kernel code, absent from the image. This assessment makes no claim about the host kernel.
- The November 1 refresh identified four newly reported pyasn1 findings, fixed by updating to 0.6.5. The final repaired-image scan has 385 findings (371 HIGH, 14 CRITICAL), all in the already reviewed kernel-header set. Its digest is `sha256:88305bdd47854ad08ae8800b6c8309d198d5b6c2ff78b16108353faafab5ec67`.
- The owner explicitly approved the scoped exception during the November 1 voice conversation. It is implemented with exact digest/package/CVE binding and a six-hour expiry. The actual scan passes only under this explicit exception. All other findings remain blocked. See [the review and expiry](runtime-review.md).
- The native SageMaker definition, separate processing roles, real-model evaluation worker, managed MLflow reporting and approval-gated publisher are implemented. Local SDK-shape checks pass; these new components have not been exercised together in AWS.
- Both assistant services, their containers, read-only tool dispatch, IAM roles, Kubernetes manifests and Argo CD applications are implemented. A Linux-container check verified HTTP authentication, a synthetic response, an MLflow trace ID and release identifiers. It did not call a real model or SageMaker.
- AWS read-only checks on November 1 found no EKS clusters, no active Astra-tagged instances and no in-progress SageMaker Processing jobs in us-east-1.

The lab is **not yet classroom ready**. Live evaluation/promotion, two-zone serving, real assistant tool calls, the student walkthrough, recovery and cleanup verification remain open. The foundation plan has 141 creations, no deletions and no GPU resources. Only the private operator IAM resources have been applied. Additional rehearsal budget approval was requested before cluster creation because delayed billing is close to the recorded earlier test ceiling. Use [Model Release Pipeline](model-release-pipeline.md) and [Serving Deployment](serving-deployment.md) for the new implementation. The sections below preserve the earlier live results.

The live test was stopped at the owner's request. AWS verification confirmed that the temporary EKS cluster, instances, RDS, Redis, MLflow, load balancer, NAT gateways and VPC are gone. The final database snapshot, monitoring snapshots, evidence/model buckets, image repositories and storage encryption key were retained. Storage charges can continue. This is not an end-to-end verified lab. The results below describe observations before teardown; the temporary addresses are no longer available.

## A. Verified so far

- The Python tests pass locally, including Gateway API rendering, browser authentication configuration and the model API's separate route.
- Terraform completed the private EKS foundation with two CPU workers and GPU capacity in both zones, private RDS and Redis, storage and Cognito.
- The private operator connected to EKS. The NVIDIA device plugin advertised one GPU on each GPU worker. A Kubernetes diagnostic job on the first GPU successfully ran nvidia-smi and reported an NVIDIA L40S with no uncorrectable ECC errors.
- Cert-manager issued the load-balancer controller's internal certificates. Argo CD, the load-balancer controller and External Secrets Operator deployed successfully.
- External Secrets Operator synchronized the model API key from AWS Secrets Manager with a role limited to that one secret. Its value was not placed in Git or printed.
- The Argo CD Gateway API route was accepted, the ALB target became healthy, and ExternalDNS created the records. The updated route opens Argo CD's own login directly over HTTPS, without Cognito. A fresh request returned HTTP 200 and the browser displayed the native login. Signing in to administer Argo CD is still pending.
- The EBS CSI add-on became Active. Argo CD deployed Grafana, Prometheus and Alertmanager; all their pods became Ready and the Grafana and Prometheus volumes became Bound. Grafana DNS, HTTPS and administrator sign-in passed. Its route sends an unauthenticated request directly to Grafana's own /login page, without Cognito. DCGM exporter is running on both GPU workers, and Prometheus returned a separate utilization series for each NVIDIA L40S. Model workload measurements are still pending.
- LiteLLM's initializer completed, External Secrets synchronized its configuration, and both gateway replicas became Ready in separate zones. Native browser login passed without Cognito. The public model API rejected a request without a key with HTTP 401. Argo CD reports the corrected gateway deployment Healthy and Synced.
- The managed MLflow server reached Created and Active. Its former launcher reached the managed UI after sign-in. A live API test created a run, metric and artifact and read the artifact back. Two prompt versions were visible in the browser. These were connectivity tests, not model evaluations.
- The pinned Qwen candidate was downloaded and its publisher hashes verified. The intake Job completed and wrote a versioned quarantine manifest. The scan gate found clean GuardDuty events for all 76 exact artifact versions. The model is still unapproved and has not been served.

## October 29 release blocker

Trivy 0.76.1 scanned the pinned vLLM 0.32.0 image and reported 392 HIGH and 17 CRITICAL findings, representing 397 distinct vulnerability IDs. The release check failed. Of the findings, 386 refer to the linux-libc-dev header package and need applicability review; they are not evidence that a kernel shipped inside the container is running. Other findings include Python and operating-system dependencies with available fixes. Do not treat the image as approved, hide the results or bypass the check. A repaired image needs a new digest, scan and compatibility test.

A patched runtime candidate failed its dependency check because its updated OpenTelemetry packages conflict with LMCache's constraints. It was not deployed, promoted or included as a working image in the starter.

These results do not prove model inference, application behavior or recovery.

## B. Corrections found during the live run

- Use an explicit KUBECONFIG path when the shell or operator session already sets one. Pass the same path to aws eks update-kubeconfig.
- Install the NVIDIA device plugin with k8s/device-plugin-values.yaml. Its default node affinity expects labels that this foundation does not create. The supplied values select the GPU workers and tolerate their GPU taint.
- A GPU type listed in an Availability Zone can still be unavailable when you launch it. One zone rejected the requested size for insufficient capacity. A reviewed larger instance with the same GPU launched successfully through gpu_instance_type_overrides. Do not treat a quota increase as a fix for physical capacity.
- With ACM, set the certificate in LoadBalancerConfiguration. An empty Gateway tls block with mode Terminate fails Gateway API validation; it must not be generated.
- Use Gateway API resources throughout routing and cleanup. Do not delete the complete generated routes bundle during route cleanup, because it contains application namespaces.
- Create the EBS CSI add-on and its role in Terraform before syncing monitoring. Synchronize the Grafana administrator secret through External Secrets Operator before the chart starts.
- The live SageMaker API rejected an explicit MLflow version of 3.0.0. Omitting the requested version created the server, and AWS reported version 3.0.0. The template exposes an optional version input and records the resolved server version. The pinned MLflow client and SageMaker plugin completed the live connectivity check.
- Publishing a LiteLLM route previously changed its Deployment and triggered an extra pod that could not fit on the CPU workers. Routing now leaves that Deployment to Argo CD. Gateway rolling updates replace one replica at a time and preserve one available replica. The corrected live rollout completed.
- Route publication now labels existing application namespaces without replacing their Argo CD annotations.
- The LiteLLM root opens Swagger by default. The route generator now redirects only that hostname's exact root path to /ui/. The separate /v1 inference route is unchanged. Local tests pass; the redirect was not applied live because deployment work had been stopped for cleanup.
- The two-GPU serving template now replaces one replica at a time. Its former surge setting required a third GPU. The corrected model rollout remains untested because the model was not deployed.
- The Python dependency lock originally included an unconditional Windows package. The universal lock preserves platform markers, and GitHub's Linux checks passed after the correction.

The tested device-plugin installation is:

```bash
helm repo add nvdp https://nvidia.github.io/k8s-device-plugin
helm upgrade --install nvidia-device-plugin nvdp/nvidia-device-plugin \
  --namespace gpu-system --create-namespace --version 0.20.1 \
  --values k8s/device-plugin-values.yaml --wait --timeout 10m
```

## C. Live checks still open after local implementation

- Two-zone model inference and failover.
- Argo CD administrator sign-in and completed access checks for the assistants.
- The consolidated bootstrap script from a fresh student account. Its individual controller installation steps and the Argo CD storage/monitoring definitions were exercised live; the full student path still needs its own run.
- All remaining application secret values and their synchronization.
- Live provisioning and execution of the newly implemented SageMaker validation/evaluation pipeline and approval-gated publisher.
- Full assistant traces, tool spans, feedback and release lineage in MLflow remain unverified. The selected browser access is now SageMaker Studio from the AWS console. Studio user access and that console walkthrough remain unverified.
- Live deployment of the new model and assistant containers and Argo CD configuration.
- Authenticated model responses, assistant tool calls, shared gateway limits, monitoring, alerts and recovery exercises.

Start an independent review with the repository and Terraform foundation. Use your own operator role, private connectivity, domain, certificate and AWS credentials. Keep the local state for cleanup. Stop at any missing prerequisite and record the exact failing step; do not interpret a generated file or a passing unit test as evidence that a service was deployed.

MLflow has been removed from the custom hostname catalog, Cognito callbacks and Kubernetes deployment definitions. The managed tracking server and application tracking integration remain.
