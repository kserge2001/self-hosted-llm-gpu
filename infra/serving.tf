resource "aws_iam_role" "serving" {
  name = "${var.name}-serving"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity",
    Principal = { Federated = module.eks.oidc_provider_arn },
    Condition = { StringEquals = {
      "${local.dns_oidc_issuer}:sub" = "system:serviceaccount:llm:vllm",
      "${local.dns_oidc_issuer}:aud" = "sts.amazonaws.com"
    } }
  }] })
}

resource "aws_iam_role_policy" "serving" {
  role = aws_iam_role.serving.id
  name = "read-promoted-models-only"
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = "s3:GetObjectVersion", Resource = "${aws_s3_bucket.data["release"].arn}/releases/*" },
    { Effect = "Allow", Action = "kms:Decrypt", Resource = aws_kms_key.platform.arn,
    Condition = { StringEquals = { "kms:ViaService" = "s3.us-east-1.amazonaws.com" } } }
  ] })
}

resource "aws_iam_role" "assistant" {
  for_each = toset(["k8s-assistant", "aws-assistant"])
  name     = "${var.name}-${each.key}"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity",
    Principal = { Federated = module.eks.oidc_provider_arn },
    Condition = { StringEquals = {
      "${local.dns_oidc_issuer}:sub" = "system:serviceaccount:${each.key}:${each.key}",
      "${local.dns_oidc_issuer}:aud" = "sts.amazonaws.com"
    } }
  }] })
}

resource "aws_iam_role_policy" "assistant" {
  for_each = aws_iam_role.assistant
  role     = each.value.id
  name     = "read-only-tools-and-traces"
  policy = jsonencode({ Version = "2012-10-17", Statement = concat([
    { Effect = "Allow", Action = ["sagemaker-mlflow:GetExperimentByName", "sagemaker-mlflow:GetExperiment", "sagemaker-mlflow:CreateExperiment",
      "sagemaker-mlflow:GetRegisteredModel", "sagemaker-mlflow:GetModelVersion", "sagemaker-mlflow:StartTrace", "sagemaker-mlflow:EndTrace",
    "sagemaker-mlflow:GetTraceInfo", "sagemaker-mlflow:SetTraceTag"], Resource = aws_sagemaker_mlflow_tracking_server.astra.arn },
    { Effect = "Allow", Action = ["s3:PutObject", "s3:GetObject"], Resource = "${aws_s3_bucket.data["mlflow"].arn}/artifacts/*" },
    { Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey"], Resource = aws_kms_key.platform.arn,
    Condition = { StringEquals = { "kms:ViaService" = "s3.us-east-1.amazonaws.com" } } }
    ], each.key == "aws-assistant" ? [
    { Effect = "Allow", Action = "ec2:DescribeInstances", Resource = "*", Condition = { StringEquals = { "aws:RequestedRegion" = "us-east-1" } } }
  ] : []) })
}

output "serving_role_arn" { value = aws_iam_role.serving.arn }
output "assistant_roles" { value = { for name, role in aws_iam_role.assistant : name => role.arn } }
