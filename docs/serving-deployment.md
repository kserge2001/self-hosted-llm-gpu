# Deploy the approved model and assistants

This path has local implementation checks but still requires a live rehearsal. Start with the versioned release produced by [Model Release Pipeline](model-release-pipeline.md).

## Prepare application identities

Create one LiteLLM application key for each assistant, limited to the `astra` model with classroom request/token limits. Store each key as `{"OPENAI_API_KEY":"..."}` in that assistant's Terraform-created Secrets Manager secret. Do not use the gateway master key in an assistant. Synchronize the secrets with the existing External Secrets configuration before starting the pods.

The Kubernetes assistant can list pods, describe deployments and read recent events only in `synthetic`; the AWS assistant can describe EC2 instances in us-east-1 and filters its results to the Astra tag. Neither role grants infrastructure write permissions. They use separate IAM roles, service accounts and application keys.

Register each reviewed prompt against the active managed MLflow server:

```bash
export MLFLOW_TRACKING_ARN=YOUR_TRACKING_SERVER_ARN
python register_prompt.py --kind kubernetes > evidence/kubernetes-prompt.json
python register_prompt.py --kind aws > evidence/aws-prompt.json
```

Keep each prompt record: numeric URI, exact text, content hash and experiment ID. Registration reads the exact version back from MLflow before producing the record. The deployment bundles that text in an immutable ConfigMap with a name derived from its hash. The assistant refuses to start if its bundled text differs from the pinned hash; starting an existing release does not fetch a prompt or look up an experiment in MLflow. Its trace records the application image, application commit, prompt URI/hash, model release, tool schema hash. Raw questions and tool responses are not recorded by this implementation; inspect the synthetic response in the application and use the trace for call order and identities. A returned trace ID alone does not prove successful export: open the real request's trace in MLflow.

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
| `prompts` | Objects named `kubernetes` and `aws`, each with the registered `uri`, `sha256`, `template` and `experiment_id` |

```bash
python prepare_deployment.py evidence/deployment-config.json --output deploy > evidence/rendered-release.json
```

This reads and verifies the exact promoted manifest, then renders `deploy/model` and `deploy/assistants`. It does not deploy. Review the YAML and commit it through the GitOps review process. No secret values belong in these directories. The renderer refuses to overwrite an existing release; preserve the previous manifests for rollback before preparing an update.

## Start only when the release is ready

Prepare the first model deployment with `python prepare_deployment.py --component model --release evidence/promoted-release.json`. This reads the saved foundation outputs and `evidence/images.json`; assistant prompts are not required for the first model response. Commit the rendered model files, then enable the reviewed GPU capacity through Terraform. Render and apply `argocd/model.yaml` with the repository URL and reviewed Git revision.

After the first response, prepare the complete assistant settings and use `python prepare_deployment.py evidence/deployment-config.json --component assistants`. Commit those generated files, then render and apply `argocd/assistants.yaml`. This keeps the working model deployment intact while adding the applications. The Astra AppProject permits both sets of namespaces.

Sync `astra-model` and watch its loader logs. Each loader reads exact S3 versions and verifies hashes before writing the release identity. Both vLLM replicas must become Ready in separate zones. Then sync `astra-assistants` and confirm both replicas of each assistant are Ready. Publish the assistant routes using the existing domain configuration workflow.

An incomplete loader download requires a new Pod with an empty model volume after correcting the error. Do not treat a partial model directory as valid. The non-root loader uses the pod's shared filesystem group for its model volume.

## Complete the classroom walkthrough

Follow [Platform Verification](acceptance-checks.md) with synthetic requests: authenticated inference, separate application usage, both assistants' tool calls and trace IDs, prompt versions and live GPU monitoring. Confirm the forbidden Kubernetes namespace and AWS write actions are denied. Use [Troubleshooting](troubleshooting-recovery.md) if a step fails, then run [Cleanup](cleanup.md) after the walkthrough.

Keep all live results unchecked until observed. Neither container builds nor synthetic local trace tests certify this path as classroom ready.
