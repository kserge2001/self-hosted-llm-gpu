locals {
  application_secrets = {
    llm           = "vllm-key"
    gateway       = "litellm-env"
    k8s-assistant = "k8s-assistant-env"
    aws-assistant = "aws-assistant-env"
    monitoring    = "grafana-admin"
  }
}

# Values are written through Secrets Manager, never through tfvars or Git.
resource "aws_secretsmanager_secret" "application" {
  for_each                = local.application_secrets
  name_prefix             = "${var.name}/${each.key}/${each.value}-"
  recovery_window_in_days = 7
}

resource "aws_iam_role" "secret_reader" {
  for_each = local.application_secrets
  name     = "${var.name}-${each.key}-secrets"
  assume_role_policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = module.eks.oidc_provider_arn }
      Condition = { StringEquals = {
        "${local.dns_oidc_issuer}:sub" = "system:serviceaccount:${each.key}:astra-secret-reader"
        "${local.dns_oidc_issuer}:aud" = "sts.amazonaws.com"
      } }
    }]
  })
}

resource "aws_iam_role_policy" "secret_reader" {
  for_each = local.application_secrets
  role     = aws_iam_role.secret_reader[each.key].id
  name     = "read-one-application-secret"
  policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
      Resource = aws_secretsmanager_secret.application[each.key].arn
    }]
  })
}

output "application_secrets" {
  value = { for namespace, name in local.application_secrets : namespace => {
    namespace       = namespace, target_name = name
    secret_arn      = aws_secretsmanager_secret.application[namespace].arn
    reader_role_arn = aws_iam_role.secret_reader[namespace].arn
  } }
}
