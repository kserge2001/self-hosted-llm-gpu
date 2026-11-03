# Astra AWS Console companion

This is the manual reference for the AWS resources in Astra's two-zone design. It uses the current AWS documentation checked on November 3, 2026. It does not use Terraform commands.

**Scope:** AWS resource creation and inspection. The AWS Console does not replace the supplied kubectl/Helm bootstrap for this self-managed Argo CD, LiteLLM, vLLM, and monitoring deployment. The [Kodelumi course](https://kodelumi.com/w/49_OMkQYNp9zuC57) contains that working command path. A completely click-only deployment of the unchanged stack has not been established. Do not treat this companion as proof of a second end-to-end deployment route.

Use one provisioning route for a stack. If Terraform already created it, use these screens to inspect it rather than create a second copy.

## 1. Record the values that connect the screens

Select **US East (N. Virginia), us-east-1**. Record your stack name, AWS account, two Availability Zones, operator IAM principal, domain, existing hosted-zone ID, and issued wildcard certificate ARN. Use `Project=astra` and the stack name to identify your resources.

Keep a local record of the IDs returned by each creation screen. Later services need the actual subnet, security-group, bucket, key, and role identifiers, not their display labels. Do not copy the instructor's account identifiers.

The course's tested deployment uses EKS 1.35, two `m6i.large` CPU workers, two independently scheduled `g6e.xlarge` model workers, RDS PostgreSQL 17, Redis OSS 7.1, and a Small managed MLflow server. GPU availability must be confirmed at launch. Keep GPU workers off until model files and the server image are prepared.

## 2. Create the two-zone network

Open **VPC → Your VPCs → Create VPC**. Choose **VPC and more**, a name based on your stack, IPv4 CIDR `10.40.0.0/16`, two zones, two public subnets, and two private application subnets. Choose one NAT gateway per zone, enable DNS hostnames and DNS resolution, and select an S3 gateway endpoint. Review the resource map before creating it. [AWS creation procedure](https://docs.aws.amazon.com/vpc/latest/userguide/create-vpc.html).

Use these subnet ranges to match the starter:

| Purpose | First zone | Second zone |
| --- | --- | --- |
| Public ALB and NAT | `10.40.0.0/24` | `10.40.1.0/24` |
| Private EKS and CloudShell | `10.40.16.0/20` | `10.40.32.0/20` |
| Private database/cache | `10.40.64.0/24` | `10.40.65.0/24` |

Create the two database subnets through **VPC → Subnets → Create subnet**. Associate them with route tables that keep the stores private. Each application subnet's default route uses its own zone's NAT gateway. Public subnet routes use the internet gateway.

Tag public subnets `kubernetes.io/role/elb=1` and application subnets `kubernetes.io/role/internal-elb=1`. Associate the S3 gateway endpoint with the application-subnet route tables. The [private-subnet example](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-example-private-subnets-nat.html) explains the NAT layout.

**Check:** Two independent NAT paths exist. Application and database resources receive no public IP address.

## 3. Create the encryption key and private storage

In **KMS → Customer managed keys → Create key**, choose a symmetric encrypt/decrypt key. Assign a stack-specific alias, keep an authorized key administrator, and enable rotation. Record its ARN. The workload roles need only their documented use of this key; key-administration permission is separate.

In **S3 → Buckets → Create bucket**, create four globally unique general-purpose bucket names for `quarantine`, `release`, `evidence`, and `mlflow`. Keep Block Public Access enabled and ACLs disabled. Enable versioning and default SSE-KMS encryption using the platform key; enable S3 Bucket Keys. Add an HTTPS-only bucket policy for each bucket. These controls correspond to the supplied [storage definitions](../infra/foundation.tf). [AWS bucket creation](https://docs.aws.amazon.com/AmazonS3/latest/userguide/create-bucket-overview.html).

Quarantine stores incoming files. Release stores the versions used for serving. Evidence stores file-check and operator records. MLflow stores artifacts. None is a public model-download endpoint.

In **ECR → Private repositories → Create repository**, create `<stack>/loader`, `<stack>/evaluation`, and `<stack>/assistant`. Select immutable tags, KMS encryption, and scanning on push. The `evaluation` repository name is a retained infrastructure identifier used by the runtime and validator images; it does not add a student evaluation exercise. [AWS ECR procedure](https://docs.aws.amazon.com/AmazonECR/latest/userguide/repository-create.html).

**Check:** Record bucket names, key ARN, and registry URLs. Image pushing and model downloading are performed by the supplied course helpers, not by a Console upload form.

## 4. Create the EKS control plane and its access

In **IAM → Roles**, create the EKS cluster service role using the EKS service trust and `AmazonEKSClusterPolicy`. Create worker roles with the EC2 service trust and the EKS worker and ECR pull permissions described in [AWS's node-role documentation](https://docs.aws.amazon.com/eks/latest/userguide/create-node-role.html). Configure the VPC CNI permissions using the documented node-role or dedicated service-account role path; do not omit them.

Open **EKS → Clusters → Create cluster** (some views show **Add cluster → Create**). Select **Custom configuration** and turn **Use EKS Auto Mode** off. Enter the stack name, EKS 1.35, cluster role, and both application subnets. Set API endpoint access to **Private**. Enable API, audit, authenticator, controller-manager, and scheduler logs. Review compatible VPC CNI, CoreDNS, and kube-proxy add-ons. [AWS cluster creation](https://docs.aws.amazon.com/eks/latest/userguide/create-cluster.html).

On the cluster's **Access** page, create a **Standard** access entry for the approved operator IAM principal and associate `AmazonEKSClusterAdminPolicy` at cluster scope. Use the underlying IAM role or user ARN, not an STS session ARN. [EKS access entries](https://docs.aws.amazon.com/eks/latest/userguide/access-entries.html).

Allow HTTPS from `10.40.16.0/20` to the cluster API security group for the CloudShell connection. Keep the endpoint private. [Private endpoint requirements](https://docs.aws.amazon.com/eks/latest/userguide/cluster-endpoint.html).

**Check:** The cluster becomes Active. Its endpoint is private and the intended operator appears under Access.

## 5. Add the CPU workers, then prepare the GPU groups

Open the cluster's **Compute → Node groups → Add node group**. Create one CPU group in each application subnet. Choose the appropriate node IAM role, AL2023 x86-64 standard AMI, `m6i.large`, desired/minimum 1, maximum 3, and encrypted 80-GiB gp3 root storage. Apply the Kubernetes label `astra/tier=cpu`. Do not enable SSH access. Record the worker security group used by the nodes. [AWS node-group procedure](https://docs.aws.amazon.com/eks/latest/userguide/create-managed-node-group.html).

For exact encryption and volume settings, use the EC2 launch-template section offered by the node-group creation flow. When supplying a launch template, follow the [EKS launch-template requirements](https://docs.aws.amazon.com/eks/latest/userguide/launch-templates.html); do not independently set conflicting AMI or network-interface settings.

After model preparation, create one GPU group per zone with AL2023 x86-64 NVIDIA AMI, `g6e.xlarge`, desired/minimum 1, maximum 2, and encrypted 200-GiB gp3 root storage. Label it `astra/tier=gpu` and add taint `nvidia.com/gpu=true` with effect **NoSchedule**. Each group uses only its zone's application subnet.

The supplied NVIDIA device-plugin installation advertises the GPU to Kubernetes. A node appearing in EC2 does not prove that vLLM has loaded the model.

**Check:** CPU nodes are Ready in both zones. Later, confirm both GPU nodes and the two model replicas. A single successful GPU remains a single-replica result.

## 6. Create the private gateway stores

Create a dedicated stores security group. Allow TCP 5432 and 6379 only from the actual worker security group. Do not allow a public CIDR. Create RDS and ElastiCache subnet groups containing the two database subnets.

In **RDS → Databases → Create database**, choose **Standard create**, PostgreSQL 17, and **Multi-AZ DB instance deployment**. Use identifier `<stack>-gateway`, class `db.t4g.small`, encrypted gp3 storage starting at 30 GiB with a 100-GiB autoscaling limit, database name `litellm`, and master username `astra_admin`. Let Secrets Manager manage the master password. Select the platform KMS key, private subnet group, stores security group, and **Public access: No**. Keep seven-day backups and deletion protection. Use a PostgreSQL 17 parameter group with `rds.force_ssl=1`. [RDS settings](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_CreateDBInstance.Settings.html).

In **ElastiCache → Redis OSS caches → Create Redis OSS cache**, choose to configure a node-based cluster with cluster mode disabled. Set Redis OSS 7.1, `cache.t4g.small`, one primary plus one replica across the two zones, Multi-AZ and automatic failover enabled, the private subnet group, and stores security group. Enable at-rest encryption with the platform key and required in-transit encryption. Configure AUTH and keep its credential in the stack's Secrets Manager Redis secret. Keep a one-day snapshot retention. [Redis OSS creation](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/SubnetGroups.designing-cluster-pre.redis.html).

**Check:** Both services become Available, remain private, and have their standby/replica in the other zone. Record endpoints and secret ARNs, never passwords in the guide.

## 7. Connect the workload identities and file checks

The starter uses IRSA. Open the EKS cluster's OIDC issuer, then register that issuer in **IAM → Identity providers → Add provider**, with type OpenID Connect and audience `sts.amazonaws.com`. Each workload role trusts only its matching namespace/service account and audience. [AWS OIDC setup](https://docs.aws.amazon.com/eks/latest/userguide/enable-iam-roles-for-service-accounts.html).

The following supplied definitions are the policy source for recreating these roles. Their Terraform expressions must be resolved to your actual bucket, key, secret, OIDC, zone, and tracking-server identifiers before entering JSON in **IAM → Roles → Create role → Custom trust policy**, followed by **Add permissions → Create inline policy → JSON**. HCL cannot be pasted into the IAM JSON editor.

| Workload | Required source and boundary |
| --- | --- |
| Load balancer controller | [Controller role and policy](../infra/load-balancer-controller.tf); manages the stack's ALB resources |
| ExternalDNS | [Domain roles](../infra/domains.tf); changes only the selected hosted zone and service records |
| EBS CSI | [Storage-driver role](../infra/storage-driver.tf); provisions encrypted persistent volumes |
| Model intake | [Intake role](../infra/model-scanning.tf); uploads candidate files to quarantine |
| Serving loader | [Serving role](../infra/serving.tf); reads exact model versions from release storage |
| Secret readers | [Application secrets](../infra/application-secrets.tf); one role per namespace, one secret each |
| Gateway initializer | [Gateway bootstrap](../infra/gateway-bootstrap.tf); initializes the database login and application secrets |
| Assistants | [Assistant roles](../infra/serving.tf); bounded infrastructure tools and MLflow operations |
| MLflow service | [MLflow role](../infra/mlflow.tf); access to its artifact bucket and encryption key |
| Supplied file checks | [Processing and publication roles](../infra/model-pipeline.tf); CPU validation and versioned file publication |

In **GuardDuty → Malware Protection for S3**, enable protection for the quarantine bucket using the scanner role and enable result tagging. In **EventBridge → Rules**, send that bucket's GuardDuty object-scan-result events to `/astra/<stack>/model-scans` in CloudWatch Logs. Retain logs for 30 days. The event target needs permission to write the log group. Match the [supplied scan-event definitions](../infra/model-scanning.tf), including the bucket filter. [AWS S3 malware protection](https://docs.aws.amazon.com/guardduty/latest/ug/gdu-malware-protection-s3.html).

**Boundary:** This reference does not supply a separately rendered, account-specific IAM policy package or a replacement for `foundation-outputs.json`. Those are required before the existing deployment helpers can consume a manually created foundation. The Terraform course route supplies both. Do not launch a separate manual stack expecting the helpers to discover these values automatically.

## 8. Configure browser sign-in and MLflow

In **Cognito → User pools**, create the stack's dashboard pool with administrator-created users only. Create a confidential app client for the ALB, use the authorization-code grant and `openid` scope, and create a Cognito domain. Configure these callback paths on your own assistant hosts:

- `https://k8sassistant.YOUR_DOMAIN/oauth2/idpresponse`
- `https://awsassistant.YOUR_DOMAIN/oauth2/idpresponse`

Use the two assistant roots as sign-out URLs. The supplied ALB routes read the pool ARN, client ID, and domain; they do not use a browser-embedded client secret. Argo CD, Grafana and LiteLLM use separate application logins. [ALB authentication requirements](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/listener-authenticate-users.html).

For managed MLflow, use **SageMaker AI Studio → Applications → MLflow → Create MLflow Tracking Server**. Set a stack-specific name, size **Small**, artifact location `s3://YOUR_MLFLOW_BUCKET/artifacts`, and the MLflow service role. Keep automatic model registration off. Record the selected server version and ARN. The Studio path requires an existing authorized Studio domain/profile; the course's CLI path does not. [Create through Studio](https://docs.aws.amazon.com/sagemaker/latest/dg/mlflow-create-tracking-server-studio.html).

**Check:** The user can open MLflow. Prompt versions and traces appear only after the assistant exercise sends them.

## 9. Inspect the deployed application

After the supplied Kubernetes steps, open **EKS → your cluster → Resources → Workloads → Deployments**. Inspect `vllm`, `litellm`, and the assistants. Use **Compute → Nodes** to check their zones. The Resources page is an inspection view, not the installation step for these Helm charts. [AWS resource viewer](https://docs.aws.amazon.com/eks/latest/userguide/view-kubernetes-resources.html).

In **EC2 → Load Balancers**, inspect the stack's ALB, HTTPS listener, certificate, and healthy target groups. In Route 53, inspect the generated application records. Do not independently edit controller-managed listeners or DNS while reconciliation is active.

Open the assistant, Grafana and MLflow interfaces as described in the course. Send a request to Astra and confirm it responds. Check current GPU measurements and the assistant's trace. Seeing an Active cluster alone is not the lab's acceptance result.

## 10. Clean up the manual resources

Export MLflow and save the model/version records first. Remove application HTTPRoutes while ExternalDNS and the load balancer controller still run; wait for their DNS and ALB resources to disappear. Remove the dedicated workloads and record retained EBS volume IDs.

Then use the AWS Console to delete the dedicated node groups and cluster, CloudShell VPC environment, stopped MLflow server, cache, and database after creating the intended encrypted final snapshot and disabling deletion protection. Delete the NAT gateways and release their Elastic IPs after dependent resources are gone. Remove the empty VPC's dedicated endpoints, subnets, route tables, and internet gateway. Keep the existing domain and certificate.

Retain the model/evidence buckets, images, encryption keys, logs, and selected snapshots. Only delete recorded disposable EBS volumes after they detach. Review remaining resources and billing; retained storage can still cost money. A manual stack is not tracked by the Terraform cleanup helper.

## Verification record

The resource settings above were compared with the starter and current AWS documentation. This Console route has not been deployed end to end. The November 2 live evidence belongs to the Terraform-based course run with one serving GPU, not to this manual companion. Completing a wholly click-only equivalent would require a supported bootstrap and input-generation path; changing to managed Argo CD would change the current design and is not silently substituted here.
