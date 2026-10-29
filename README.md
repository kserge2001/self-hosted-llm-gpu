# Astra platform starter

CareCart's AI Platform Engineering team is researching, designing and building an internal inference platform on AWS. Its internal model is Astra.

This starter provides the AWS foundation, model intake checker and the PR-to-SageMaker trigger. Follow the [lab in Kodelumi](https://kodelumi.com/w/49_OMkQYNp9zuC57) for the full build.

The e2e/astra branch contains the current code for independent testing. Import that branch's latest changes, not an older main snapshot. Live AWS validation is in progress. Read [what has been tested and what is still missing](docs/validation-status.md) before provisioning; this is not yet a complete, verified end-to-end release.

Start by [importing the starter into your own GitHub account](docs/repository-setup.md). Your pull requests, GitHub Actions, AWS OIDC trust and Argo CD deployments must use your imported repository. After the import finishes, get a local working copy of your repository and create the Python environment using that guide.

Python implementations are supplied as repository files. Kubernetes manifests and Helm values are under k8s/.

Routing uses Kubernetes Gateway API: a shared HTTPS Gateway and one HTTPRoute per application, backed by an AWS Application Load Balancer. Browser routes require Cognito sign-in; the inference route uses application keys. Gateway API routing is locally tested and awaits live HTTPS and sign-in verification.

Use the focused guides for [application onboarding](docs/application-onboarding.md), [platform verification](docs/acceptance-checks.md), [troubleshooting and recovery](docs/troubleshooting-recovery.md), and [cleanup](docs/cleanup.md).

## A. See the foundation

![AWS foundation](docs/aws-foundation.png)

The editable diagram is docs/aws-foundation.drawio. The first Terraform apply creates one m6i.large CPU worker and one GPU worker per Availability Zone. Verify the workers and GPU access before moving to model release and deployment. RDS and Redis are separate managed services in private data subnets; MLflow is managed by SageMaker.

Terraform state stays locally in infra/terraform.tfstate. Keep it and its backup through cleanup. State and plan files can contain credentials and are excluded from Git.

Set domain_name, subdomains and public_client_cidrs in infra/terraform.tfvars. Set acm_certificate_arn to an existing us-east-1 wildcard certificate, or leave it unset to select an issued wildcard for that domain. Terraform also creates Cognito sign-in with matching callback URLs. configure_domains.py consumes the applied outputs, generates and applies the HTTPS routes and ExternalDNS configuration. Follow [Platform addresses](docs/domain-configuration.md) for setup and verification. Live DNS, login and application checks are still required.

## B. Understand the PR process

1. Create a branch and change the code or add a model release request.
2. Open a pull request. The checks job tests Python, checks release requests and validates Terraform. It uses a GitHub-hosted runner and receives no AWS credentials.
3. A reviewer approves the change and the required checks pass. Merge into main.
4. For a new releases/*.json file, the model workflow selects that request. The astra-deploy environment holds the AWS job for approval when required reviewers are configured.
5. After approval, a GitHub-hosted runner obtains temporary AWS credentials through GitHub OIDC and starts the pinned SageMaker pipeline.
6. Argo CD pulls reviewed deployment configuration into EKS. CI does not need network access to the private Kubernetes API. The model workflow records the execution ARN and ends. SageMaker continues independently. Open that execution to inspect its steps and open MLflow to inspect evaluation results.
7. A passing candidate still requires model-package approval and a separate promotion step before serving. Starting the pipeline is not successful evaluation or release approval.

Infrastructure PRs validate configuration. Terraform apply and destroy run from the engineer's local directory so they use the same local state.

## C. Run the local checks

Use Python 3.13 for the full locked environment. The metadata intake script alone supports Python 3.10 or later. CI uses Python 3.13 and Terraform 1.15.9. Shell examples use Bash.

```bash
python -m unittest discover -s tests -v
python release_requests.py validate
terraform -chdir=infra init -backend=false -lockfile=readonly
terraform -chdir=infra fmt -check
terraform -chdir=infra validate
```

The tests do not call AWS or download model weights. Terraform initialization downloads the pinned providers and modules. Validation does not provision resources.

## D. Configure your own repository

Use your own AWS account, credentials and repository. Configure these before submitting a real release request:

- Protect main with a required pull request, an approving review and the checks status check. Restrict bypass permissions. Make protection active before merging release requests.
- Protect changes to .github/workflows and release scripts with the platform team's code-owner review. Replace the starter's CODEOWNERS entry with your actual authorized reviewers.
- Create the astra-deploy environment, allow main only, and configure the required deployment reviewers. Availability of these protections depends on your GitHub plan and repository visibility; do not assume they are active.
- Configure Argo CD to pull the reviewed deployment configuration from your repository. Restrict its AppProject to the platform destinations.
- Set the environment variable DEPLOY_ROLE_ARN to the role allowed to start and describe this pipeline. Restrict its OIDC trust to repo:OWNER/REPOSITORY:environment:astra-deploy and audience sts.amazonaws.com.
- Create the astra-model-release SageMaker Pipeline and record its version. Its definition must accept ReleaseId, CandidateManifest, CandidateManifestVersion and CandidateManifestSha256.
- Prepare the versioned S3 candidate manifest and record its SHA-256 fingerprint. It must identify the actual candidate objects and evidence.

The starter does not create GitHub rules, reviewer assignments, OIDC trust, Argo CD applications or a SageMaker pipeline automatically. These require your account-specific configuration. The full scanning and evaluation job definitions must exist before the trigger can run; the trigger does not replace them.

## E. Submit a model release through a PR

First replace the example values with the reviewed pipeline version, S3 URI, S3 object version and SHA-256 fingerprint. The example is deliberately invalid until completed.

```bash
git switch -c release/astra-001
cp examples/release-request.json releases/astra-001.json
# Edit releases/astra-001.json with the actual reviewed values.
python release_requests.py validate
python -m unittest discover -s tests -v
git add releases/astra-001.json
git commit -m "Request Astra model release astra-001"
git push -u origin release/astra-001
```

Open a pull request to main in GitHub. Review the candidate evidence, wait for checks, and merge after approval. Then open Actions, Astra model pipeline, and approve the environment job if you are an authorized reviewer. Keep its SageMaker execution ARN with the release record.

For an authorized retry, use Run workflow on main and provide an existing reviewed release ID. An identical request uses the same idempotency token to avoid unintentionally starting a duplicate execution. To intentionally evaluate again with changed inputs, submit a new release ID through a PR.

## F. Provision and clean up

Copy infra/terraform.tfvars.example to infra/terraform.tfvars and replace every REPLACE value. Follow AWS Foundation for those values and private Kubernetes access. Terraform looks up compatible component versions; save resolved_versions as versions.auto.tfvars.json after applying to fix those selections for subsequent runs. Keep .terraform.lock.hcl in version control.

Before destruction, remove dependent workloads and retain the evidence required by the lab. Run the reviewed destroy plan from the same infra directory and keep the local state until cleanup is verified. Do not delete the state file instead of deleting AWS resources.

No AWS resources are created by cloning this repository or running its local Python tests.
