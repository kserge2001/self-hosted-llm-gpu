locals {
  guardduty_rule_arn = "arn:aws:events:us-east-1:${data.aws_caller_identity.platform.account_id}:rule/DO-NOT-DELETE-AmazonGuardDutyMalwareProtectionS3*"
}

resource "aws_iam_role" "model_scanner" {
  name = "${var.name}-model-scanner"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Action = "sts:AssumeRole"
    Principal = { Service = "malware-protection-plan.guardduty.amazonaws.com" }
  }] })
}

resource "aws_iam_role_policy" "model_scanner" {
  role = aws_iam_role.model_scanner.id
  name = "scan-one-quarantine-bucket"
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["events:PutRule", "events:DeleteRule", "events:PutTargets", "events:RemoveTargets"], Resource = local.guardduty_rule_arn,
    Condition = { StringEquals = { "events:ManagedBy" = "malware-protection-plan.guardduty.amazonaws.com" } } },
    { Effect = "Allow", Action = ["events:DescribeRule", "events:ListTargetsByRule"], Resource = local.guardduty_rule_arn },
    { Effect = "Allow", Action = ["s3:ListBucket", "s3:PutBucketNotification", "s3:GetBucketNotification"], Resource = aws_s3_bucket.data["quarantine"].arn },
    { Effect = "Allow", Action = "s3:PutObject", Resource = "${aws_s3_bucket.data["quarantine"].arn}/malware-protection-resource-validation-object" },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObjectTagging", "s3:GetObjectTagging", "s3:PutObjectVersionTagging", "s3:GetObjectVersionTagging"], Resource = "${aws_s3_bucket.data["quarantine"].arn}/*" },
    { Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey"], Resource = aws_kms_key.platform.arn,
    Condition = { StringEquals = { "kms:ViaService" = "s3.us-east-1.amazonaws.com" } } }
  ] })
}

# Preserve the service's scan events independently of editable S3 object tags.
resource "aws_cloudwatch_log_group" "model_scans" {
  name              = "/astra/${var.name}/model-scans"
  retention_in_days = 30
}

resource "aws_cloudwatch_event_rule" "model_scans" {
  name = "${var.name}-model-scan-results"
  event_pattern = jsonencode({
    source        = ["aws.guardduty"]
    "detail-type" = ["GuardDuty Malware Protection Object Scan Result"]
    account       = [data.aws_caller_identity.platform.account_id]
    detail        = { s3ObjectDetails = { bucketName = [aws_s3_bucket.data["quarantine"].id] } }
  })
}

resource "aws_cloudwatch_log_resource_policy" "model_scans" {
  policy_name = "${var.name}-guardduty-scan-events"
  policy_document = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Principal = { Service = ["events.amazonaws.com", "delivery.logs.amazonaws.com"] }
    Action    = ["logs:CreateLogStream", "logs:PutLogEvents"]
    Resource  = "${aws_cloudwatch_log_group.model_scans.arn}:*"
    Condition = { ArnEquals = { "aws:SourceArn" = aws_cloudwatch_event_rule.model_scans.arn } }
  }] })
}

resource "aws_cloudwatch_event_target" "model_scans" {
  rule       = aws_cloudwatch_event_rule.model_scans.name
  arn        = aws_cloudwatch_log_group.model_scans.arn
  depends_on = [aws_cloudwatch_log_resource_policy.model_scans]
}

resource "aws_guardduty_malware_protection_plan" "quarantine" {
  role = aws_iam_role.model_scanner.arn
  protected_resource {
    s3_bucket { bucket_name = aws_s3_bucket.data["quarantine"].id }
  }
  actions    = [{ tagging = [{ status = "ENABLED" }] }]
  depends_on = [aws_iam_role_policy.model_scanner, aws_cloudwatch_event_target.model_scans]
}

resource "aws_iam_role" "model_intake" {
  name = "${var.name}-model-intake"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity"
    Principal = { Federated = module.eks.oidc_provider_arn }
    Condition = { StringEquals = {
      "${local.dns_oidc_issuer}:sub" = "system:serviceaccount:model-intake:model-intake"
      "${local.dns_oidc_issuer}:aud" = "sts.amazonaws.com"
    } }
  }] })
}

resource "aws_iam_role_policy" "model_intake" {
  role = aws_iam_role.model_intake.id
  name = "upload-quarantine-only"
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:PutObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts", "s3:GetObject"], Resource = "${aws_s3_bucket.data["quarantine"].arn}/candidates/*" },
    { Effect = "Allow", Action = ["kms:Encrypt", "kms:GenerateDataKey", "kms:Decrypt"], Resource = aws_kms_key.platform.arn,
    Condition = { StringEquals = { "kms:ViaService" = "s3.us-east-1.amazonaws.com" } } }
  ] })
}

output "model_scanning" {
  value = {
    protection_plan_id  = aws_guardduty_malware_protection_plan.quarantine.id
    protection_plan_arn = "arn:aws:guardduty:us-east-1:${data.aws_caller_identity.platform.account_id}:malware-protection-plan/${aws_guardduty_malware_protection_plan.quarantine.id}"
    protection_status   = aws_guardduty_malware_protection_plan.quarantine.status
    event_log_group     = aws_cloudwatch_log_group.model_scans.name
    intake_role_arn     = aws_iam_role.model_intake.arn
  }
}
