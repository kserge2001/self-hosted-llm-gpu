variable "domain_name" {
  description = "Existing public Route 53 zone that you control."
  type        = string
  validation {
    condition = length(var.domain_name) <= 180 && length(split(".", var.domain_name)) >= 2 && alltrue([
      for label in split(".", var.domain_name) : length(label) <= 63 && can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", label))
    ])
    error_message = "Use a lowercase DNS domain without a scheme, wildcard or trailing dot."
  }
}

variable "route53_zone_id" {
  description = "Optional existing public zone ID; useful when multiple zones have the same name."
  type        = string
  default     = null
}

variable "acm_certificate_arn" {
  description = "Existing us-east-1 certificate ARN; null selects an issued wildcard for domain_name."
  type        = string
  default     = null
  validation {
    condition     = var.acm_certificate_arn == null ? true : can(regex("^arn:aws:acm:us-east-1:[0-9]{12}:certificate/[a-f0-9-]+$", var.acm_certificate_arn))
    error_message = "Use an ACM certificate ARN in us-east-1."
  }
}

variable "subdomains" {
  description = "Override only the service labels you want to change. Unspecified services keep their defaults."
  type        = map(string)
  default     = {}
  validation {
    condition = alltrue([
      for key, label in var.subdomains : contains(["inference", "litellm", "argocd", "k8s_assistant", "aws_assistant", "grafana"], key) && can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", label)) && length(label) <= 63
    ])
    error_message = "Use a known service key and a single DNS label covered by the wildcard certificate."
  }
}

variable "public_client_cidrs" {
  description = "Approved public developer and application IPv4 egress ranges for HTTPS access."
  type        = list(string)
  validation {
    condition = length(var.public_client_cidrs) > 0 && alltrue([
      for cidr in var.public_client_cidrs : can(cidrnetmask(cidr)) && try(tonumber(split("/", cidr)[1]) > 0, false)
    ])
    error_message = "Provide explicit IPv4 client CIDRs; 0.0.0.0/0 is not allowed."
  }
}

variable "browser_auth" {
  description = "Approved ALB browser sign-in settings. Secrets remain in Kubernetes, never in tfvars."
  type = object({
    type       = string
    parameters = map(string)
  })
  default = null
  validation {
    condition = var.browser_auth == null ? true : (
      var.browser_auth.type == "cognito" ? toset(keys(var.browser_auth.parameters)) == toset(["userPoolARN", "userPoolClientID", "userPoolDomain"]) : (
        var.browser_auth.type == "oidc" ? toset(keys(var.browser_auth.parameters)) == toset(["issuer", "authorizationEndpoint", "tokenEndpoint", "userInfoEndpoint", "secretName"]) : false
      )
    )
    error_message = "Use Cognito pool/client/domain settings or OIDC HTTPS endpoints and a Kubernetes secretName."
  }
}

data "aws_route53_zone" "platform" {
  zone_id      = var.route53_zone_id
  name         = var.route53_zone_id == null ? "${var.domain_name}." : null
  private_zone = false
  lifecycle {
    postcondition {
      condition     = trimsuffix(self.name, ".") == var.domain_name && !self.private_zone
      error_message = "The selected Route 53 zone must be public and match domain_name."
    }
  }
}

data "aws_acm_certificate" "wildcard" {
  count       = var.acm_certificate_arn == null ? 1 : 0
  domain      = "*.${var.domain_name}"
  statuses    = ["ISSUED"]
  most_recent = true
}

locals {
  service_labels = merge({
    inference     = "astra"
    litellm       = "litellm"
    argocd        = "argocd"
    k8s_assistant = "k8sassistant"
    aws_assistant = "awsassistant"
    grafana       = "grafana"
  }, var.subdomains)
  service_hosts       = { for service, label in local.service_labels : service => "${label}.${var.domain_name}" }
  tls_certificate_arn = var.acm_certificate_arn != null ? var.acm_certificate_arn : data.aws_acm_certificate.wildcard[0].arn
  # Let private applications use the same HTTPS endpoint through this VPC's NATs.
  https_client_cidrs = distinct(concat(var.public_client_cidrs, [for ip in module.vpc.nat_public_ips : "${ip}/32"]))
  dns_record_names = flatten([
    for host in values(local.service_hosts) : [host, "_astra-a.${host}", "_astra-aaaa.${host}", "_astra-cname.${host}"]
  ])
  dns_oidc_issuer = trimprefix(module.eks.cluster_oidc_issuer_url, "https://")
}

resource "aws_iam_role" "external_dns" {
  name_prefix = "${var.name}-dns-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = module.eks.oidc_provider_arn }
      Condition = { StringEquals = {
        "${local.dns_oidc_issuer}:sub" = "system:serviceaccount:external-dns:external-dns"
        "${local.dns_oidc_issuer}:aud" = "sts.amazonaws.com"
      } }
    }]
  })
}

resource "aws_iam_role_policy" "external_dns" {
  name = "platform-records-only"
  role = aws_iam_role.external_dns.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["route53:ListHostedZones", "route53:ListHostedZonesByName"], Resource = "*" },
      { Effect = "Allow", Action = ["route53:ListResourceRecordSets", "route53:ListTagsForResource"], Resource = data.aws_route53_zone.platform.arn },
      {
        Effect = "Allow", Action = "route53:ChangeResourceRecordSets", Resource = data.aws_route53_zone.platform.arn
        Condition = { "ForAllValues:StringEquals" = {
          "route53:ChangeResourceRecordSetsNormalizedRecordNames" = local.dns_record_names
          "route53:ChangeResourceRecordSetsRecordTypes"           = ["A", "AAAA", "CNAME", "TXT"]
        } }
      }
    ]
  })
}

output "domain_configuration" {
  value = {
    domain_name           = var.domain_name
    zone_id               = data.aws_route53_zone.platform.zone_id
    hosts                 = local.service_hosts
    urls                  = { for service, host in local.service_hosts : service => "https://${host}${service == "inference" ? "/v1" : ""}" }
    acm_certificate_arn   = local.tls_certificate_arn
    allowed_cidrs         = local.https_client_cidrs
    cluster_name          = module.eks.cluster_name
    cluster_endpoint      = module.eks.cluster_endpoint
    external_dns_role_arn = aws_iam_role.external_dns.arn
    txt_owner_id          = "astra-${module.eks.cluster_name}"
    browser_auth          = local.effective_browser_auth
    browser_callback_urls = local.browser_callback_urls
  }
  precondition {
    condition     = length(distinct(values(local.service_labels))) == length(local.service_labels)
    error_message = "Each service must have a different hostname, including default labels."
  }
}
