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

Before syncing astra-monitoring, install the EBS CSI driver and verify its AWS role, synchronize the grafana-admin secret, and wait for astra-storage to be Healthy and Synced. These dependencies are required; a StorageClass alone cannot create volumes. The initial monitoring sync is manual so you can confirm these prerequisites.

Open astra-monitoring, inspect the proposed resources and select Sync. Its pinned Prometheus chart reads k8s/monitoring-values.yaml from your repository. Check PVCs are Bound and the application becomes Healthy and Synced. Then publish the Grafana route with configure_domains.py and sign in through its configured hostname.

Application sync-wave annotations alone do not enforce readiness between independent applications. Complete the storage and secret checks before the first monitoring sync.

## D. Make later changes through a PR

Change the relevant YAML or Helm values in your repository, open a PR and review the diff. After merging, refresh the application in Argo CD and review and sync the change. Avoid a separate helm upgrade for an application Argo CD manages, because it would create a second source of configuration.

The monitoring and storage applications are the first GitOps definitions. Model, gateway and assistant deployment applications still need their complete release configuration before they can be registered and verified.
