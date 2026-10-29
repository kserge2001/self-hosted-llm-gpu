variable "create_cognito" {
  description = "Create the lab's dashboard sign-in. Set false when supplying an approved existing browser_auth provider."
  type        = bool
  default     = true
}

locals {
  create_dashboard_pool = var.create_cognito && var.browser_auth == null
  browser_callback_urls = [for key, host in local.service_hosts : "https://${host}/oauth2/idpresponse" if !contains(["inference", "argocd", "grafana", "litellm"], key)]
  effective_browser_auth = var.browser_auth != null ? var.browser_auth : (local.create_dashboard_pool ? {
    type = "cognito"
    parameters = {
      userPoolARN      = aws_cognito_user_pool.dashboards[0].arn
      userPoolClientID = aws_cognito_user_pool_client.dashboards[0].id
      userPoolDomain   = aws_cognito_user_pool_domain.dashboards[0].domain
    }
  } : null)
}

resource "random_id" "cognito_domain" {
  count       = local.create_dashboard_pool ? 1 : 0
  byte_length = 4
}

resource "aws_cognito_user_pool" "dashboards" {
  count = local.create_dashboard_pool ? 1 : 0
  name  = "${var.name}-dashboards"
  admin_create_user_config {
    allow_admin_create_user_only = true
  }
  password_policy {
    minimum_length                   = 14
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    require_uppercase                = true
    temporary_password_validity_days = 1
  }
  username_configuration {
    case_sensitive = false
  }
  account_recovery_setting {
    recovery_mechanism {
      name     = "admin_only"
      priority = 1
    }
  }
}

resource "aws_cognito_user_pool_client" "dashboards" {
  count                                = local.create_dashboard_pool ? 1 : 0
  name                                 = "${var.name}-alb"
  user_pool_id                         = aws_cognito_user_pool.dashboards[0].id
  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = local.browser_callback_urls
  logout_urls                          = [for key, host in local.service_hosts : "https://${host}/" if !contains(["inference", "argocd", "grafana", "litellm"], key)]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  explicit_auth_flows                  = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
}

resource "aws_cognito_user_pool_domain" "dashboards" {
  count        = local.create_dashboard_pool ? 1 : 0
  domain       = "${var.name}-${random_id.cognito_domain[0].hex}"
  user_pool_id = aws_cognito_user_pool.dashboards[0].id
}

output "dashboard_user_pool_id" {
  value = local.create_dashboard_pool ? aws_cognito_user_pool.dashboards[0].id : null
}
