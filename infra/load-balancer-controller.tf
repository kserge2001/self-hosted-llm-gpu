data "aws_caller_identity" "platform" {}

resource "aws_iam_role" "load_balancer_controller" {
  name_prefix = "${var.name}-lbc-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = module.eks.oidc_provider_arn }
      Condition = { StringEquals = {
        "${local.dns_oidc_issuer}:sub" = "system:serviceaccount:kube-system:aws-load-balancer-controller"
        "${local.dns_oidc_issuer}:aud" = "sts.amazonaws.com"
      } }
    }]
  })
}

resource "aws_iam_role_policy" "load_balancer_controller" {
  name = "astra-load-balancers"
  role = aws_iam_role.load_balancer_controller.id
  policy = templatefile("${path.module}/policies/load-balancer-controller.json.tftpl", {
    account_id    = data.aws_caller_identity.platform.account_id
    cluster_name  = var.name
    node_group_id = module.eks.node_security_group_id
    certificate   = local.tls_certificate_arn
    cognito_pool  = try(local.effective_browser_auth.parameters.userPoolARN, "arn:aws:cognito-idp:us-east-1:${data.aws_caller_identity.platform.account_id}:userpool/unused")
  })
}

output "load_balancer_controller_role" {
  value = aws_iam_role.load_balancer_controller.arn
}
