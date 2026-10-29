mock_provider "aws" {
  mock_data "aws_route53_zone" {
    defaults = { name = "example.com.", zone_id = "Z123456", arn = "arn:aws:route53:::hostedzone/Z123456", private_zone = false }
  }
  mock_data "aws_ssm_parameter" {
    defaults = { value = "1.35.0-20261001" }
  }
  mock_data "aws_eks_addon_version" {
    defaults = { version = "v1.0.0-eksbuild.1" }
  }
  mock_data "aws_rds_engine_version" {
    defaults = { version_actual = "17.6", parameter_group_family = "postgres17" }
  }
}
mock_provider "random" {}

override_module {
  target = module.vpc
  outputs = {
    vpc_id           = "vpc-0123456789abcdef0", private_subnets = ["subnet-11111111", "subnet-22222222"]
    database_subnets = ["subnet-33333333", "subnet-44444444"], private_route_table_ids = ["rtb-11111111"]
    nat_public_ips   = ["198.51.100.20", "198.51.100.21"]
  }
}
override_module {
  target = module.eks
  outputs = {
    cluster_name            = "astra-test", cluster_endpoint = "https://test.eks.amazonaws.com"
    oidc_provider_arn       = "arn:aws:iam::123456789012:oidc-provider/oidc.eks.us-east-1.amazonaws.com/id/TEST"
    cluster_oidc_issuer_url = "https://oidc.eks.us-east-1.amazonaws.com/id/TEST"
    node_security_group_id  = "sg-0123456789abcdef0"
  }
}

variables {
  name                = "astra-test"
  azs                 = ["us-east-1a", "us-east-1b"]
  operator_role_arn   = "arn:aws:iam::123456789012:role/operator"
  operator_cidr       = "10.40.0.0/16"
  gpu_instance_type   = "g6e.2xlarge"
  domain_name         = "example.com"
  public_client_cidrs = ["203.0.113.10/32"]
  acm_certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/01234567-0123-0123-0123-0123456789ab"
}

run "partial_override_and_cognito_callbacks" {
  command = plan
  variables { subdomains = { mlflow = "models" } }
  assert {
    condition     = output.domain_configuration.hosts.mlflow == "models.example.com" && output.domain_configuration.hosts.argocd == "argocd.example.com" && length(output.domain_configuration.hosts) == 7
    error_message = "Partial overrides must retain every other hostname."
  }
  assert {
    condition     = contains(output.domain_configuration.allowed_cidrs, "198.51.100.20/32") && contains(output.domain_configuration.allowed_cidrs, "203.0.113.10/32")
    error_message = "Include the workstation and VPC NAT addresses."
  }
  assert {
    condition     = contains(aws_cognito_user_pool_client.dashboards[0].callback_urls, "https://models.example.com/oauth2/idpresponse") && length(aws_cognito_user_pool_client.dashboards[0].callback_urls) == 3 && !contains(aws_cognito_user_pool_client.dashboards[0].callback_urls, "https://argocd.example.com/oauth2/idpresponse") && !contains(aws_cognito_user_pool_client.dashboards[0].callback_urls, "https://grafana.example.com/oauth2/idpresponse") && !contains(aws_cognito_user_pool_client.dashboards[0].callback_urls, "https://litellm.example.com/oauth2/idpresponse")
    error_message = "Browser callbacks must exclude the model API and dashboards with their own login."
  }
}

run "reject_duplicate_default_label" {
  command = plan
  variables { subdomains = { mlflow = "argocd" } }
  expect_failures = [output.domain_configuration]
}

run "reject_nested_label" {
  command = plan
  variables { subdomains = { mlflow = "models.internal" } }
  expect_failures = [var.subdomains]
}
