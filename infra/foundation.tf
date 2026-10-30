terraform {
  required_version = ">= 1.10.0, < 2.0.0"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "6.70.0" }
    random = { source = "hashicorp/random", version = "3.9.1" }
  }
}
provider "aws" {
  region = "us-east-1"
  default_tags { tags = { Project = "astra", ManagedBy = "Terraform", Environment = "development" } }
}
variable "name" {
  type = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,26}$", var.name))
    error_message = "Use a lowercase name up to 27 characters so the ALB name fits its limit."
  }
}
variable "azs" {
  type = list(string)
  validation {
    condition     = length(distinct(var.azs)) == 2
    error_message = "Select two distinct us-east-1 Availability Zones with the candidate GPU offering."
  }
}
variable "operator_role_arn" { type = string }
variable "operator_cidr" { type = string }
variable "gpu_instance_type" { type = string }
variable "gpu_instance_type_overrides" {
  description = "Optional per-zone replacement when the selected instance size has no capacity. Use a reviewed GPU-compatible size."
  type        = map(string)
  default     = {}
}
variable "gpu_enabled" {
  type    = bool
  default = true
}
variable "cpu_ami_release" {
  type    = string
  default = null
}
variable "gpu_ami_release" {
  type    = string
  default = null
}
variable "addon_versions" {
  type    = map(string)
  default = {}
}
variable "postgres_version" {
  type    = string
  default = null
}
variable "redis_version" {
  type    = string
  default = "7.1"
}
variable "database_deletion_protection" {
  description = "Disable only for approved teardown after deciding what data to retain."
  type        = bool
  default     = true
}
variable "retain_final_database_snapshot" {
  description = "Keep a final database snapshot during teardown. False is for disposable test data only."
  type        = bool
  default     = true
}

data "aws_eks_addon_version" "selected" {
  for_each           = toset(["vpc-cni", "coredns", "kube-proxy"])
  addon_name         = each.key
  kubernetes_version = "1.35"
  most_recent        = false
}
data "aws_ssm_parameter" "worker_release" {
  for_each        = toset(["standard", "nvidia"])
  name            = "/aws/service/eks/optimized-ami/1.35/amazon-linux-2023/x86_64/${each.key}/recommended/release_version"
  with_decryption = false
}
data "aws_rds_engine_version" "postgres" {
  engine                 = "postgres"
  parameter_group_family = "postgres17"
  latest                 = true
}
locals {
  cpu_ami_release = var.cpu_ami_release != null ? var.cpu_ami_release : nonsensitive(data.aws_ssm_parameter.worker_release["standard"].value)
  gpu_ami_release = var.gpu_ami_release != null ? var.gpu_ami_release : nonsensitive(data.aws_ssm_parameter.worker_release["nvidia"].value)
  addon_versions = {
    for name, selected in data.aws_eks_addon_version.selected :
    name => lookup(var.addon_versions, name, selected.version)
  }
  postgres_version = var.postgres_version != null ? var.postgres_version : data.aws_rds_engine_version.postgres.version_actual
}

module "vpc" {
  source                 = "terraform-aws-modules/vpc/aws"
  version                = "6.7.0"
  name                   = var.name
  cidr                   = "10.40.0.0/16"
  azs                    = var.azs
  public_subnets         = ["10.40.0.0/24", "10.40.1.0/24"]
  private_subnets        = ["10.40.16.0/20", "10.40.32.0/20"]
  database_subnets       = ["10.40.64.0/24", "10.40.65.0/24"]
  enable_nat_gateway     = true
  one_nat_gateway_per_az = true
  enable_dns_hostnames   = true
  enable_dns_support     = true
  private_subnet_tags    = { "kubernetes.io/role/internal-elb" = "1" }
  public_subnet_tags     = { "kubernetes.io/role/elb" = "1" }
}
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = module.vpc.vpc_id
  service_name      = "com.amazonaws.us-east-1.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = module.vpc.private_route_table_ids
}
module "eks" {
  source                                   = "terraform-aws-modules/eks/aws"
  version                                  = "21.29.0"
  name                                     = var.name
  kubernetes_version                       = "1.35"
  endpoint_private_access                  = true
  endpoint_public_access                   = false
  vpc_id                                   = module.vpc.vpc_id
  subnet_ids                               = module.vpc.private_subnets
  enable_irsa                              = true
  enable_cluster_creator_admin_permissions = false
  enabled_log_types                        = ["api", "audit", "authenticator", "controllerManager", "scheduler"]
  access_entries = {
    operator = {
      principal_arn = var.operator_role_arn
      policy_associations = {
        operator = {
          policy_arn   = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
          access_scope = { type = "cluster" }
        }
      }
    }
  }
  security_group_additional_rules = {
    operator = {
      description = "Approved private operator route"
      type        = "ingress", protocol = "tcp", from_port = 443, to_port = 443
      cidr_blocks = [var.operator_cidr]
    }
  }
  addons = {
    for name, version in local.addon_versions : name => {
      addon_version        = version
      before_compute       = contains(["vpc-cni", "eks-pod-identity-agent"], name)
      configuration_values = name == "vpc-cni" ? jsonencode({ enableNetworkPolicy = "true" }) : null
    }
  }
  eks_managed_node_groups = merge({
    for index, az in var.azs : "cpu-${index}" => {
      subnet_ids          = [module.vpc.private_subnets[index]]
      ami_type            = "AL2023_x86_64_STANDARD"
      ami_release_version = local.cpu_ami_release
      instance_types      = ["m6i.large"]
      min_size            = 1, max_size = 3, desired_size = 1
      labels              = { "astra/tier" = "cpu" }
      block_device_mappings = { root = {
        device_name = "/dev/xvda"
        ebs         = { volume_size = 80, volume_type = "gp3", encrypted = true, delete_on_termination = true }
      } }
    }
    }, var.gpu_enabled ? {
    for index, az in var.azs : "gpu-${index}" => {
      subnet_ids          = [module.vpc.private_subnets[index]]
      ami_type            = "AL2023_x86_64_NVIDIA"
      ami_release_version = local.gpu_ami_release
      instance_types      = [lookup(var.gpu_instance_type_overrides, az, var.gpu_instance_type)]
      min_size            = 1, max_size = 2, desired_size = 1
      block_device_mappings = { root = {
        device_name = "/dev/xvda"
        ebs         = { volume_size = 200, volume_type = "gp3", encrypted = true, delete_on_termination = true }
      } }
      labels = { "astra/tier" = "gpu" }
      taints = { gpu = { key = "nvidia.com/gpu", value = "true", effect = "NO_SCHEDULE" } }
    }
  } : {})
}
resource "aws_kms_key" "platform" {
  description             = "Astra storage and database encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}
resource "aws_s3_bucket" "data" {
  for_each      = toset(["quarantine", "release", "evidence", "mlflow"])
  bucket_prefix = "${var.name}-${each.key}-"
  force_destroy = false
}
resource "aws_s3_bucket_public_access_block" "data" {
  for_each                = aws_s3_bucket.data
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_versioning" "data" {
  for_each = aws_s3_bucket.data
  bucket   = each.value.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  for_each = aws_s3_bucket.data
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.platform.arn
    }
    bucket_key_enabled = true
  }
}
resource "aws_s3_bucket_policy" "tls" {
  for_each = aws_s3_bucket.data
  bucket   = each.value.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Sid       = "DenyInsecureTransport", Effect = "Deny", Principal = "*", Action = "s3:*"
    Resource  = [each.value.arn, "${each.value.arn}/*"]
    Condition = { Bool = { "aws:SecureTransport" = "false" } }
  }] })
}
resource "aws_security_group" "stores" {
  name_prefix = "${var.name}-stores-"
  vpc_id      = module.vpc.vpc_id
}
resource "aws_vpc_security_group_ingress_rule" "store" {
  for_each                     = { postgres = 5432, redis = 6379 }
  security_group_id            = aws_security_group.stores.id
  referenced_security_group_id = module.eks.node_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = each.value
  to_port                      = each.value
}
resource "aws_db_subnet_group" "gateway" {
  name       = "${var.name}-gateway"
  subnet_ids = module.vpc.database_subnets
}
resource "aws_db_parameter_group" "gateway" {
  name_prefix = "${var.name}-pg-"
  family      = "postgres17"
  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "pending-reboot"
  }
}
resource "aws_db_instance" "gateway" {
  identifier                  = "${var.name}-gateway"
  engine                      = "postgres"
  engine_version              = local.postgres_version
  instance_class              = "db.t4g.small"
  allocated_storage           = 30
  max_allocated_storage       = 100
  storage_type                = "gp3"
  storage_encrypted           = true
  kms_key_id                  = aws_kms_key.platform.arn
  db_name                     = "litellm"
  username                    = "astra_admin"
  manage_master_user_password = true
  db_subnet_group_name        = aws_db_subnet_group.gateway.name
  parameter_group_name        = aws_db_parameter_group.gateway.name
  vpc_security_group_ids      = [aws_security_group.stores.id]
  publicly_accessible         = false
  multi_az                    = true
  backup_retention_period     = 7
  deletion_protection         = var.database_deletion_protection
  skip_final_snapshot         = !var.retain_final_database_snapshot
  final_snapshot_identifier   = "${var.name}-gateway-final"
}
resource "random_password" "redis" {
  length  = 40
  special = false
}
resource "aws_elasticache_subnet_group" "gateway" {
  name       = "${var.name}-gateway"
  subnet_ids = module.vpc.database_subnets
}
resource "aws_elasticache_replication_group" "gateway" {
  replication_group_id        = "${var.name}-gateway"
  description                 = "Shared Astra gateway counters"
  engine                      = "redis"
  engine_version              = var.redis_version
  node_type                   = "cache.t4g.small"
  parameter_group_name        = "default.redis7"
  num_cache_clusters          = 2
  preferred_cache_cluster_azs = var.azs
  automatic_failover_enabled  = true
  multi_az_enabled            = true
  subnet_group_name           = aws_elasticache_subnet_group.gateway.name
  security_group_ids          = [aws_security_group.stores.id]
  at_rest_encryption_enabled  = true
  transit_encryption_enabled  = true
  transit_encryption_mode     = "required"
  kms_key_id                  = aws_kms_key.platform.arn
  auth_token                  = random_password.redis.result
  snapshot_retention_limit    = 1
}
resource "aws_secretsmanager_secret" "redis" {
  name_prefix             = "${var.name}/redis-"
  kms_key_id              = aws_kms_key.platform.arn
  recovery_window_in_days = 7
}
resource "aws_secretsmanager_secret_version" "redis" {
  secret_id     = aws_secretsmanager_secret.redis.id
  secret_string = random_password.redis.result
}
resource "aws_ecr_repository" "images" {
  for_each             = toset(["loader", "evaluation", "assistant"])
  name                 = "${var.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.platform.arn
  }
  force_delete = false
}
output "cluster" { value = module.eks.cluster_name }
output "operator_role_arn" { value = var.operator_role_arn }
output "buckets" { value = { for k, v in aws_s3_bucket.data : k => v.bucket } }
output "private_subnets" { value = module.vpc.private_subnets }
output "vpc" { value = module.vpc.vpc_id }
output "kms_key" { value = aws_kms_key.platform.arn }
output "postgres_host" { value = aws_db_instance.gateway.address }
output "postgres_admin_secret" { value = aws_db_instance.gateway.master_user_secret[0].secret_arn }
output "redis_host" { value = aws_elasticache_replication_group.gateway.primary_endpoint_address }
output "redis_secret" { value = aws_secretsmanager_secret.redis.arn }
output "oidc_provider_arn" { value = module.eks.oidc_provider_arn }
output "oidc_issuer" { value = module.eks.cluster_oidc_issuer_url }
output "node_security_group" { value = module.eks.node_security_group_id }
output "images" { value = { for k, v in aws_ecr_repository.images : k => v.repository_url } }
output "resolved_versions" {
  value = {
    cpu_ami_release  = local.cpu_ami_release
    gpu_ami_release  = local.gpu_ami_release
    addon_versions   = local.addon_versions
    postgres_version = local.postgres_version
    redis_version    = var.redis_version
  }
}
