# Deploy the approved model and assistants

This path has local implementation checks but still requires a live rehearsal. Start with the versioned release produced by [Model Release Pipeline](model-release-pipeline.md).

## Prepare application identities

Create one LiteLLM application key for each assistant, limited to the `astra` model with classroom request/token limits. Store each key as `{"OPENAI_API_KEY":"..."}` in that assistant's Terraform-created Secrets Manager secret. Do not use the gateway master key in an assistant. Synchronize the secrets with the existing External Secrets configuration before starting the pods.

The Kubernetes assistant can list pods only in `synthetic`; the AWS assistant can describe EC2 instances in us-east-1 and filters its results to the Astra tag. Neither role grants infrastructure write permissions. They use separate IAM roles, service accounts and application keys.

Register each reviewed prompt against the active managed MLflow server:

```bash
export MLFLOW_TRACKING_ARN=YOUR_TRACKING_SERVER_ARN
python register_prompt.py --kind kubernetes > evidence/kubernetes-prompt.json
python register_prompt.py --kind aws > evidence/aws-prompt.json
```

Keep each numeric URI and content hash. The assistant refuses to start if the registered prompt differs from its pinned hash. Its trace records the application image, application commit, prompt URI/hash, model release, tool schema hash and evaluation dataset hash. Raw questions and tool responses are not recorded by this implementation; inspect the synthetic response in the application and use the trace for call order and identities.

## Render the deployment for review

Create `evidence/deployment-config.json` using actual values from Terraform and the evaluated release. It needs these fields:

| Field | Source |
| --- | --- |
| `release` | Promotion result: `uri`, `version`, `sha256` |
| `release_bucket` | Terraform `buckets.release` |
| `loader_image`, `assistant_image` | Your built ECR digest URIs |
| `serving_role_arn`, `assistant_roles` | Corresponding Terraform outputs |
| `git_revision` | Full commit of the built application source |
| `mlflow_arn` | Terraform `mlflow.arn` |
| `astra_host` | Terraform `domain_configuration.hosts.inference` |
| `alb_arn` | ARN of this stack's actual shared ALB |
| `cognito_client_id` | This stack's assistant browser sign-in client |
| `prompts` | Objects named `kubernetes` and `aws`, each with the registered `uri` and `sha256` |

```bash
python prepare_deployment.py evidence/deployment-config.json --output deploy > evidence/rendered-release.json
```

This reads and verifies the exact promoted manifest, then renders `deploy/model` and `deploy/assistants`. It does not deploy. Review the YAML and commit it through the GitOps review process. No secret values belong in these directories. The renderer refuses to overwrite an existing release; preserve the previous manifests for rollback before preparing an update.

## Start only when the release is ready

Enable the reviewed GPU capacity through Terraform only after the model release, images, secrets, prompts and deployment manifests are ready. Render and apply `argocd/serving.yaml` with the repository URL and reviewed Git commit. The updated Astra AppProject permits the model and assistant namespaces.

Sync `astra-model` and watch its loader logs. Each loader reads exact S3 versions and verifies hashes before writing the release identity. Both vLLM replicas must become Ready in separate zones. Then sync `astra-assistants` and confirm both replicas of each assistant are Ready. Publish the assistant routes using the existing domain configuration workflow.

An incomplete loader download requires a new Pod with an empty model volume after correcting the error. Do not treat a partial model directory as valid. The non-root loader uses the pod's shared filesystem group for its model volume.

## Complete the classroom walkthrough

Follow [Platform Verification](acceptance-checks.md) with synthetic requests: authenticated inference, separate application usage, both assistants' tool calls and trace IDs, prompt versions, evaluation evidence and live GPU monitoring. Confirm the forbidden Kubernetes namespace and AWS write actions are denied. Test the documented recovery exercise, restore the saved release, and run [Cleanup](cleanup.md).

Keep all live results unchecked until observed. Neither container builds nor synthetic local trace tests certify this path as classroom ready.
