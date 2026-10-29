resource "aws_iam_role" "gateway_bootstrap" {
  name = "${var.name}-gateway-bootstrap"
  assume_role_policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = module.eks.oidc_provider_arn }
      Condition = { StringEquals = {
        "${local.dns_oidc_issuer}:sub" = "system:serviceaccount:gateway:gateway-bootstrap"
        "${local.dns_oidc_issuer}:aud" = "sts.amazonaws.com"
      } }
    }]
  })
}

resource "aws_iam_role_policy" "gateway_bootstrap" {
  role = aws_iam_role.gateway_bootstrap.id
  name = "initialize-gateway-credentials"
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"], Resource = [
      aws_db_instance.gateway.master_user_secret[0].secret_arn,
      aws_secretsmanager_secret.redis.arn,
      aws_secretsmanager_secret.application["gateway"].arn,
      aws_secretsmanager_secret.application["llm"].arn
    ] },
    { Effect = "Allow", Action = "secretsmanager:PutSecretValue", Resource = [
      aws_secretsmanager_secret.application["gateway"].arn,
      aws_secretsmanager_secret.application["llm"].arn
    ] },
    { Effect = "Allow", Action = "kms:Decrypt", Resource = aws_kms_key.platform.arn,
    Condition = { StringEquals = { "kms:ViaService" = "secretsmanager.us-east-1.amazonaws.com" } } }
  ] })
}

output "gateway_bootstrap_role" { value = aws_iam_role.gateway_bootstrap.arn }
