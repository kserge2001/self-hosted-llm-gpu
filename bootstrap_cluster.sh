#!/usr/bin/env bash
set -euo pipefail

# Run from the repository root after Terraform and kubeconfig setup.
export CLUSTER_NAME=$(terraform -chdir=infra output -raw cluster)
export VPC_ID=$(terraform -chdir=infra output -raw vpc)
export LOAD_BALANCER_CONTROLLER_ROLE_ARN=$(terraform -chdir=infra output -raw load_balancer_controller_role)
kubectl --context "$CLUSTER_NAME" get nodes

work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT

download() {
  curl --fail --location --silent --show-error "$1" --output "$work_dir/$2"
  printf '%s  %s\n' "$3" "$work_dir/$2" | sha256sum --check
}

download https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.0/standard-install.yaml gateway-api.yaml a557172e8348f758479e9ee4000bbbb4b4aa48302a6b73461823ea5349bad56d
download https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v3.6.2/config/crd/gateway/gateway-crds.yaml lbc-crds.yaml 3a4264e2a7cf132944fd095b04ce86299385f26ea31b1e89d0ac21761e1865a0
kubectl --context "$CLUSTER_NAME" apply --server-side -f "$work_dir/gateway-api.yaml"
kubectl --context "$CLUSTER_NAME" apply --server-side -f "$work_dir/lbc-crds.yaml"

download https://charts.jetstack.io/charts/cert-manager-v1.21.3.tgz cert-manager.tgz 9ec67938b2981d8b333af61b3fcf53e26b4f6f5deb7ccda3de4ea116bb373a17
helm upgrade --install cert-manager "$work_dir/cert-manager.tgz" --kube-context "$CLUSTER_NAME" \
  --namespace cert-manager --create-namespace --values k8s/cert-manager-values.yaml --wait --timeout 5m

download https://aws.github.io/eks-charts/aws-load-balancer-controller-3.6.2.tgz lbc.tgz 9255bf39873b6cb31106dbe61dc87c3617bff4197783b5b94381811a13f99c3c
python render_manifest.py k8s/load-balancer-controller-values.yaml "$work_dir/lbc-values.yaml"
helm upgrade --install aws-load-balancer-controller "$work_dir/lbc.tgz" --kube-context "$CLUSTER_NAME" \
  --namespace kube-system --values "$work_dir/lbc-values.yaml" --wait --timeout 5m

download https://github.com/external-secrets/external-secrets/releases/download/helm-chart-2.14.0/external-secrets-2.14.0.tgz external-secrets.tgz 0a6d9e91b1ff50adfdbf24b50b582babfa7c5b7df42b21974ca4b3fb88ee5e34
helm upgrade --install external-secrets "$work_dir/external-secrets.tgz" --kube-context "$CLUSTER_NAME" \
  --namespace external-secrets --create-namespace --values k8s/external-secrets-values.yaml --wait --timeout 5m

download https://github.com/argoproj/argo-helm/releases/download/argo-cd-10.11.6/argo-cd-10.11.6.tgz argocd.tgz d8f096d87513b41ff754053a7f9604c943bf29c15436a79226fd51595ea67d05
helm upgrade --install argocd "$work_dir/argocd.tgz" --kube-context "$CLUSTER_NAME" \
  --namespace argocd --create-namespace --values k8s/argocd-values.yaml --wait --timeout 10m

kubectl --context "$CLUSTER_NAME" -n kube-system get certificates
kubectl --context "$CLUSTER_NAME" -n external-secrets get deployments
python configure_domains.py --services argocd --apply --context "$CLUSTER_NAME"
