# Deploy through Argo CD

## A. Bootstrap once

Terraform creates the AWS resources. Configure kubeconfig, then run bootstrap_cluster.sh from the repository root with the Python environment active. It installs the controllers and Argo CD needed to start GitOps. The bootstrap uses pinned charts and checks their downloaded fingerprints.

The public ALB uses ACM. Cert-manager issues the load-balancer controller's internal certificates. External Secrets Operator synchronizes application credentials from AWS Secrets Manager using a separate, narrowly scoped role for each namespace.

## B. Register your repository

The Argo CD definitions live in argocd/platform.yaml. The application manifests and Helm values stay in k8s. Argo CD reads both directly from your imported repository. Set the repository URL and the branch you use for reviewed deployments:

```bash
export GITOPS_REPOSITORY_URL=https://github.com/YOUR_GITHUB_NAME/self-hosted-llm-gpu.git
export GITOPS_REVISION=main
mkdir -p k8s/generated
python render_manifest.py argocd/platform.yaml k8s/generated/argocd-platform.yaml
kubectl apply -f k8s/generated/argocd-platform.yaml
```

The rendering command creates a new file. If you need to change it, review the existing generated file before removing it and rendering again. Register private repository credentials through the approved secret process before syncing a private repository.

## C. Sync storage, then monitoring

Open Argo CD. The astra-storage application manages the encrypted gp3 StorageClass. It synchronizes automatically, but automatic pruning is disabled to avoid deleting storage configuration accidentally.

Terraform installs the EBS CSI driver with its own AWS role. Before syncing astra-monitoring, verify that add-on is Active, synchronize the grafana-admin secret, and wait for astra-storage to be Healthy and Synced. These dependencies are required; a StorageClass alone cannot create volumes. The initial monitoring sync is manual so you can confirm these prerequisites.

Open astra-monitoring, inspect the proposed resources and select Sync. Its pinned Prometheus chart reads k8s/monitoring-values.yaml from your repository. Check PVCs are Bound and the application becomes Healthy and Synced. Then publish the Grafana route with configure_domains.py and sign in through its configured hostname.

Application sync-wave annotations alone do not enforce readiness between independent applications. Complete the storage and secret checks before the first monitoring sync.

## D. Make later changes through a PR

Change the relevant YAML or Helm values in your repository, open a PR and review the diff. After merging, refresh the application in Argo CD and review and sync the change. Avoid a separate helm upgrade for an application Argo CD manages, because it would create a second source of configuration.

## E. Deploy the MLflow launcher

Terraform creates the managed tracking server and the launcher's AWS role. Build apps/Dockerfile.mlflow-launcher and push it to your ECR repository. Record the image digest. The small launcher verifies the signed identity from the configured ALB before issuing a temporary MLflow UI link.

Set MLFLOW_LAUNCHER_IMAGE to that digest, MLFLOW_LAUNCHER_ROLE_ARN and MLFLOW_TRACKING_SERVER_NAME from the Terraform mlflow output, EXPECTED_ALB_ARN to your platform ALB, and COGNITO_CLIENT_ID to the configured dashboard client. Reuse the repository URL and revision from section B.

```bash
python render_manifest.py argocd/mlflow.yaml k8s/generated/argocd-mlflow.yaml
kubectl apply -f k8s/generated/argocd-mlflow.yaml
```

Open astra-mlflow in Argo CD and sync it. Wait for both launcher pods and the managed server to be ready. Then publish the MLflow route with configure_domains.py. Verify the browser sign-in and redirect, and confirm a request made directly to the launcher without a signed ALB identity is rejected.

## F. Deploy LiteLLM

Build apps/Dockerfile.gateway-bootstrap and push it to ECR. This small initialization job creates the database login and stores generated application credentials in Secrets Manager. A retry keeps the same credentials. External Secrets Operator then copies the gateway configuration into its Kubernetes Secret.

The gateway chart is k8s/gateway. It includes two LiteLLM replicas, their ClusterIP Service, the initialization job and secret synchronization. The database connections verify the AWS RDS certificate. The checked-in public CA bundle comes from AWS and its origin and fingerprint are recorded in files/README.md.

Use argocd/gateway.yaml with the Terraform outputs: gateway_bootstrap_role, application_secrets, postgres_host, postgres_admin_secret, redis_host and redis_secret. Set GATEWAY_BOOTSTRAP_IMAGE to the initializer's ECR digest and LITELLM_HOST to the configured UI hostname. Reuse GITOPS_REPOSITORY_URL and GITOPS_REVISION from section B.

```bash
python render_manifest.py argocd/gateway.yaml k8s/generated/argocd-gateway.yaml
kubectl apply -f k8s/generated/argocd-gateway.yaml
```

Sync astra-gateway in Argo CD. The initialization job runs first. Wait for the secret to synchronize and both gateway pods to be Ready before publishing the inference and LiteLLM routes. The completed Job stays visible as the initialization record. It contains no credentials in its manifest or logs.

The UI and gateway health can be checked before model deployment. An actual model response requires the approved model release and healthy vLLM pods. That end-to-end check remains incomplete until it is performed.

LiteLLM opens its own login directly over HTTPS. Its chart supplies the hostname; publishing a route does not change its Deployment. Rolling updates replace one replica at a time, keeping the other available without requiring capacity for a third gateway pod.

Model and assistant deployment applications still need their complete release configuration before they can be registered and verified.
