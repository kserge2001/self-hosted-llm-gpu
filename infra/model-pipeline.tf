# Processing jobs end automatically at their configured time limit. Deploying
# these roles and the pipeline definition does not start a GPU job.
locals {
  model_pipeline_name = "${var.name}-model-release"
  model_package_group = "${var.name}-astra"
  processing_trust = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "sagemaker.amazonaws.com" }, Action = "sts:AssumeRole",
    Condition = { StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.platform.account_id },
    ArnLike = { "aws:SourceArn" = "arn:aws:sagemaker:us-east-1:${data.aws_caller_identity.platform.account_id}:*" } }
  }] })
  processing_log_arn = "arn:aws:logs:us-east-1:${data.aws_caller_identity.platform.account_id}:log-group:/aws/sagemaker/ProcessingJobs"
  package_arns = [
    "arn:aws:sagemaker:us-east-1:${data.aws_caller_identity.platform.account_id}:model-package-group/${local.model_package_group}",
    "arn:aws:sagemaker:us-east-1:${data.aws_caller_identity.platform.account_id}:model-package/${local.model_package_group}/*"
  ]
}

resource "aws_security_group" "processing" {
  name_prefix = "${var.name}-processing-"
  description = "Private SageMaker validation and evaluation jobs"
  vpc_id      = module.vpc.vpc_id
}

resource "aws_vpc_security_group_egress_rule" "processing_https" {
  security_group_id = aws_security_group.processing.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_iam_role" "processing" {
  for_each           = toset(["validation", "evaluation"])
  name               = "${var.name}-${each.key}"
  assume_role_policy = local.processing_trust
}

resource "aws_iam_role_policy" "processing" {
  for_each = aws_iam_role.processing
  name     = "bounded-model-processing"
  role     = each.value.id
  policy = jsonencode({ Version = "2012-10-17", Statement = concat([
    { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion"], Resource = [
      "${aws_s3_bucket.data["quarantine"].arn}/candidates/*", "${aws_s3_bucket.data["evidence"].arn}/runtime/*",
    "${aws_s3_bucket.data["evidence"].arn}/pipeline/*"] },
    { Effect = "Allow", Action = ["s3:ListBucket", "s3:GetBucketLocation"], Resource = [
    aws_s3_bucket.data["quarantine"].arn, aws_s3_bucket.data["evidence"].arn] },
    { Effect = "Allow", Action = ["s3:PutObject", "s3:AbortMultipartUpload"], Resource = "${aws_s3_bucket.data["evidence"].arn}/pipeline/*" },
    { Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"], Resource = aws_kms_key.platform.arn },
    { Effect = "Allow", Action = "kms:CreateGrant", Resource = aws_kms_key.platform.arn,
    Condition = { Bool = { "kms:GrantIsForAWSResource" = "true" } } },
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Action = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"],
    Resource = [for repo in aws_ecr_repository.images : repo.arn] },
    { Effect = "Allow", Action = ["logs:CreateLogGroup"], Resource = local.processing_log_arn },
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${local.processing_log_arn}:*" },
    { Effect = "Allow", Action = ["ec2:CreateNetworkInterface", "ec2:CreateNetworkInterfacePermission", "ec2:DeleteNetworkInterface",
      "ec2:DeleteNetworkInterfacePermission", "ec2:DescribeNetworkInterfaces", "ec2:DescribeVpcs", "ec2:DescribeDhcpOptions",
    "ec2:DescribeSubnets", "ec2:DescribeSecurityGroups"], Resource = "*" }
    ], each.key == "validation" ? [
    { Effect = "Allow", Action = ["logs:FilterLogEvents"], Resource = "${aws_cloudwatch_log_group.model_scans.arn}:*" }
    ] : [
    { Effect = "Allow", Action = ["sagemaker-mlflow:CreateExperiment", "sagemaker-mlflow:GetExperimentByName",
    "sagemaker-mlflow:CreateRun", "sagemaker-mlflow:LogBatch", "sagemaker-mlflow:UpdateRun"], Resource = aws_sagemaker_mlflow_tracking_server.astra.arn },
    { Effect = "Allow", Action = ["s3:PutObject"], Resource = "${aws_s3_bucket.data["mlflow"].arn}/artifacts/*" }
  ]) })
}

resource "aws_sagemaker_model_package_group" "astra" {
  model_package_group_name        = local.model_package_group
  model_package_group_description = "Astra candidates; approval is separate from evaluation and publication."
}

resource "aws_iam_role" "model_pipeline" {
  name               = "${var.name}-model-pipeline"
  assume_role_policy = local.processing_trust
}

resource "aws_iam_role_policy" "model_pipeline" {
  name = "validate-evaluate-register-only"
  role = aws_iam_role.model_pipeline.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["sagemaker:CreateProcessingJob", "sagemaker:DescribeProcessingJob", "sagemaker:StopProcessingJob", "sagemaker:AddTags"],
    Resource = "arn:aws:sagemaker:us-east-1:${data.aws_caller_identity.platform.account_id}:processing-job/*" },
    { Effect = "Allow", Action = ["sagemaker:CreateModelPackage", "sagemaker:DescribeModelPackage", "sagemaker:DescribeModelPackageGroup", "sagemaker:AddTags"],
    Resource = local.package_arns },
    { Effect = "Allow", Action = "iam:PassRole", Resource = [for role in aws_iam_role.processing : role.arn],
    Condition = { StringEquals = { "iam:PassedToService" = "sagemaker.amazonaws.com" } } },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion"], Resource = "${aws_s3_bucket.data["evidence"].arn}/pipeline/*" },
    { Effect = "Allow", Action = ["kms:Decrypt"], Resource = aws_kms_key.platform.arn },
    { Effect = "Deny", Action = ["sagemaker:UpdateModelPackage"], Resource = "*" }
  ] })
}

resource "aws_iam_role" "model_promotion" {
  name = "${var.name}-model-promotion"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Action = "sts:AssumeRole", Principal = { AWS = var.operator_role_arn }
  }] })
}

resource "aws_iam_role_policy" "model_promotion" {
  role = aws_iam_role.model_promotion.id
  name = "publish-approved-versions-only"
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = "sagemaker:DescribeModelPackage", Resource = local.package_arns },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion"], Resource = [
      "${aws_s3_bucket.data["quarantine"].arn}/candidates/*", "${aws_s3_bucket.data["evidence"].arn}/pipeline/*",
    "${aws_s3_bucket.data["release"].arn}/releases/*"] },
    { Effect = "Allow", Action = "s3:PutObject", Resource = "${aws_s3_bucket.data["release"].arn}/releases/*" },
    { Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey"], Resource = aws_kms_key.platform.arn },
    { Effect = "Deny", Action = "sagemaker:UpdateModelPackage", Resource = "*" }
  ] })
}

output "model_pipeline" {
  value = {
    pipeline_name       = local.model_pipeline_name
    pipeline_role_arn   = aws_iam_role.model_pipeline.arn
    validation_role_arn = aws_iam_role.processing["validation"].arn
    evaluation_role_arn = aws_iam_role.processing["evaluation"].arn
    promotion_role_arn  = aws_iam_role.model_promotion.arn
    model_package_group = aws_sagemaker_model_package_group.astra.model_package_group_name
    private_subnets     = module.vpc.private_subnets
    security_groups     = [aws_security_group.processing.id]
    kms_key_arn         = aws_kms_key.platform.arn
    quarantine_bucket   = aws_s3_bucket.data["quarantine"].id
    evidence_bucket     = aws_s3_bucket.data["evidence"].id
    release_bucket      = aws_s3_bucket.data["release"].id
    scan_log_group      = aws_cloudwatch_log_group.model_scans.name
    malware_plan_arn    = "arn:aws:guardduty:us-east-1:${data.aws_caller_identity.platform.account_id}:malware-protection-plan/${aws_guardduty_malware_protection_plan.quarantine.id}"
    mlflow_arn          = aws_sagemaker_mlflow_tracking_server.astra.arn
    mlflow_bucket       = aws_s3_bucket.data["mlflow"].id
  }
}
