# Platform addresses

## A. Configure the names once

Set the base domain in infra/terraform.tfvars. Use a public Route 53 zone you control and an issued wildcard ACM certificate in us-east-1. Override only the subdomain labels you want to change.

```hcl
domain_name = "afriqhome.com"
subdomains = {
  inference     = "astra"
  litellm       = "litellm"
  argocd        = "argocd"
  mlflow        = "mlflow"
  k8s_assistant = "k8sassistant"
  aws_assistant = "awsassistant"
  grafana       = "grafana"
}
create_cognito = true
```

For your implementation, replace the domain with your own. The resulting addresses are astra, litellm, argocd, mlflow, k8sassistant, awsassistant and grafana under that domain. The Astra API uses /v1. The LiteLLM dashboard uses /ui. Both reach the same gateway Service, while vLLM remains private.

Set public_client_cidrs to your approved public egress addresses. Terraform also includes the platform's NAT addresses for applications calling from private subnets. Set acm_certificate_arn to use a particular existing certificate; otherwise Terraform finds the issued wildcard. The certificate stays in ACM. This ALB listener does not need cert-manager.

Argo CD opens its own login directly over HTTPS. It does not redirect through Cognito.

Terraform creates a Cognito user pool, a client and a sign-in domain for the other five browser entry points. Public self-registration is disabled. Create approved users through Cognito administration; do not put their passwords in Terraform or Git. Application permissions inside Grafana and LiteLLM still apply. The model API uses its application key.

MLflow opens through the configured mlflow hostname, then redirects the authorized browser to SageMaker's managed UI. The browser address changes after that redirect.

## B. Generate and apply the routes

Apply the AWS foundation first. Install the standard Gateway API v1.6.0 CRDs, the AWS Load Balancer Controller v3.6.2 Gateway CRDs and the controller. Its service account needs the controller's reviewed AWS permissions through IRSA. Deploy each backend Service before publishing its route. Run from a workstation with access to the private EKS API.

The foundation now defines that controller role. bootstrap_cluster.sh contains the pinned controller, cert-manager, External Secrets Operator and Argo CD setup. Follow Argo CD deployment for the bootstrap and the first GitOps applications.

Create the local Kubernetes connection before using kubectl:

```bash
CLUSTER_NAME=$(terraform -chdir=infra output -raw cluster)
OPERATOR_ROLE_ARN=$(terraform -chdir=infra output -raw operator_role_arn)
export KUBECONFIG="$PWD/astra.kubeconfig"
aws eks update-kubeconfig --region us-east-1 --name "$CLUSTER_NAME" \
  --role-arn "$OPERATOR_ROLE_ARN" --alias "$CLUSTER_NAME" \
  --kubeconfig "$KUBECONFIG"
export CLUSTER_CONTEXT="$CLUSTER_NAME"
kubectl config current-context
```

Your AWS identity must be allowed to assume the operator role. If you already use that role, omit --role-arn. Updating kubeconfig creates the connection settings; your workstation still needs a network route to the private EKS endpoint.

```bash
source .venv/bin/activate
python configure_domains.py
```

This reads the applied Terraform output directly. It creates the ExternalDNS manifest, one HTTPS Gateway, HTTPRoutes, browser authentication settings, Argo CD and Grafana domain values, and endpoints.json under k8s/generated/edge. No hostname needs to be copied into YAML. Use the generated domain values with the corresponding Helm releases. Keep these settings in the environment's reviewed GitOps configuration so Argo CD preserves them.

After the selected services are deployed, apply the routes. Use the context created for this stack.

```bash
python configure_domains.py --apply --context "$CLUSTER_CONTEXT"
```

The script checks the cluster endpoint, Gateway API definitions, certificate coverage, existing DNS ownership, backend Service ports and browser sign-in configuration before changing Kubernetes. It installs ExternalDNS and applies the routes. AWS Load Balancer Controller creates the HTTPS listener; ExternalDNS creates the DNS records. All routes share one ALB. Only the platform team should be able to change the Gateway, HTTPRoutes, authentication settings or namespace labels that allow routes to attach.

During the gateway step, publish just the ready API service:

```bash
python configure_domains.py --services inference --apply --context "$CLUSTER_CONTEXT"
```

Selecting services only applies those routes. It does not remove previously published routes. Missing applications are reported as prerequisites, rather than treated as successful deployment.

## C. Verify the result

```bash
terraform -chdir=infra output -json domain_configuration
kubectl --context "$CLUSTER_CONTEXT" -n platform-system get gateway astra-public
kubectl --context "$CLUSTER_CONTEXT" get httproute --all-namespaces
kubectl --context "$CLUSTER_CONTEXT" -n external-dns logs deployment/external-dns --tail=50
```

Run the short OpenAI SDK example in Application Onboarding with your application key. Expect a real answer over verified HTTPS. Check that the Gateway is Programmed, the HTTPRoutes are Accepted with ResolvedRefs, and each published hostname has the expected ALB address in Route 53 with no ExternalDNS ownership error.

Open each browser hostname in a private window. Expect Cognito sign-in before application access. After approved sign-in, verify the intended application; for MLflow, verify the redirect to the managed UI. A generated YAML file, DNS record or HTTP redirect alone does not prove the application works.

If DNS is missing, inspect ExternalDNS logs and its IAM role. If a target is unhealthy, check the Service port, ready endpoints and health path. If Cognito rejects a callback, compare the URL with domain_configuration.browser_callback_urls. Do not disable TLS or sign-in to make a test pass.

## D. Change names or clean up

Before changing an existing domain or label, remove its old HTTPRoute while the old Terraform DNS permissions still exist. Wait for ExternalDNS to remove that stack's address and ownership records. Then change terraform.tfvars, apply Terraform, regenerate and apply the routes. This avoids leaving old names behind after the IAM policy moves to the new names.

During final cleanup, remove this stack's HTTPRoutes first and wait for ExternalDNS to remove their address and ownership records. Then delete the Gateway and wait for the ALB and target groups to disappear. Keep the controllers running until that completes. Retain the shared hosted zone and existing wildcard certificate.

```bash
kubectl --context "$CLUSTER_CONTEXT" get httproute -A -l "astra/platform=$CLUSTER_NAME"
kubectl --context "$CLUSTER_CONTEXT" delete httproute -A -l "astra/platform=$CLUSTER_NAME"
# Check Route 53 before deleting the Gateway.
kubectl --context "$CLUSTER_CONTEXT" -n platform-system delete gateway astra-public
```

The label selects this stack's routes even if they were published in separate stages. Do not delete the whole routes.yaml bundle: it also contains application namespaces. Remove the remaining controller configuration during final teardown after workloads and storage have been handled.
