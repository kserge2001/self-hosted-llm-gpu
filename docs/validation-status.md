# Validation status

Updated October 29, 2026. Use the latest commit on e2e/astra for independent testing. The test account's credentials, Terraform state and private configuration are not included.

## A. Verified so far

- The Python tests pass locally, including Gateway API rendering, browser authentication configuration and the model API's separate route.
- Terraform completed the private EKS foundation with two CPU workers and GPU capacity in both zones, private RDS and Redis, storage and Cognito.
- The private operator connected to EKS. The NVIDIA device plugin advertised one GPU on each GPU worker. A Kubernetes diagnostic job on the first GPU successfully ran nvidia-smi and reported an NVIDIA L40S with no uncorrectable ECC errors.
- Cert-manager issued the load-balancer controller's internal certificates. Argo CD, the load-balancer controller and External Secrets Operator deployed successfully.
- External Secrets Operator synchronized the model API key from AWS Secrets Manager with a role limited to that one secret. Its value was not placed in Git or printed.
- The Argo CD Gateway API route was accepted, the ALB target became healthy, and ExternalDNS created the records. The updated route opens Argo CD's own login directly over HTTPS, without Cognito. A fresh request returned HTTP 200 and the browser displayed the native login. Signing in to administer Argo CD is still pending.
- The EBS CSI add-on became Active. Argo CD deployed Grafana, Prometheus and Alertmanager; all their pods became Ready and the Grafana and Prometheus volumes became Bound. Grafana DNS, HTTPS and administrator sign-in passed. Its updated route sends a fresh unauthenticated request directly to Grafana's own /login page, without Cognito. GPU dashboards still need the DCGM exporter and a live model workload.

These results do not prove model inference, application behavior or recovery.

## B. Corrections found during the live run

- Use an explicit KUBECONFIG path when the shell or operator session already sets one. Pass the same path to aws eks update-kubeconfig.
- Install the NVIDIA device plugin with k8s/device-plugin-values.yaml. Its default node affinity expects labels that this foundation does not create. The supplied values select the GPU workers and tolerate their GPU taint.
- A GPU type listed in an Availability Zone can still be unavailable when you launch it. One zone rejected the requested size for insufficient capacity. A reviewed larger instance with the same GPU launched successfully through gpu_instance_type_overrides. Do not treat a quota increase as a fix for physical capacity.
- With ACM, set the certificate in LoadBalancerConfiguration. An empty Gateway tls block with mode Terminate fails Gateway API validation; it must not be generated.
- Use Gateway API resources throughout routing and cleanup. Do not delete the complete generated routes bundle during route cleanup, because it contains application namespaces.
- Create the EBS CSI add-on and its role in Terraform before syncing monitoring. Synchronize the Grafana administrator secret through External Secrets Operator before the chart starts.
- The live SageMaker API rejected an explicit MLflow version of 3.0.0. Omitting the requested version started creation and AWS reported version 3.0.0. The template exposes an optional version input and records the resolved server version; server readiness and client compatibility remain pending.

The tested device-plugin installation is:

```bash
helm repo add nvdp https://nvidia.github.io/k8s-device-plugin
helm upgrade --install nvidia-device-plugin nvdp/nvidia-device-plugin \
  --namespace gpu-system --create-namespace --version 0.20.1 \
  --values k8s/device-plugin-values.yaml --wait --timeout 10m
```

## C. Not complete or not yet verified

- Two-zone model inference and failover.
- Completed Cognito sign-in and browser checks for every application.
- The consolidated bootstrap script from a fresh student account. Its individual controller installation steps and the Argo CD storage/monitoring definitions were exercised live; the full student path still needs its own run.
- All remaining application secret values and their synchronization.
- A complete provisioned SageMaker scanning, evaluation and promotion pipeline. The repository currently includes the trigger and supporting scripts, not the complete pipeline definition.
- Managed MLflow server creation is in progress. Launcher deployment and prompt and trace workflows in that live server are not verified.
- The complete container build and Argo CD deployment configuration for the model, gateway and assistants.
- Authenticated model responses, assistant tool calls, shared gateway limits, monitoring, alerts and recovery exercises.
- Final cleanup of this test run.

Start an independent review with the repository and Terraform foundation. Use your own operator role, private connectivity, domain, certificate and AWS credentials. Keep the local state for cleanup. Stop at any missing prerequisite and record the exact failing step; do not interpret a generated file or a passing unit test as evidence that a service was deployed.
