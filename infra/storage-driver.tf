variable "ebs_csi_version" {
  description = "Tested EBS CSI add-on version for Kubernetes 1.35."
  type        = string
  default     = "v1.67.2-eksbuild.1"
}

resource "aws_iam_role" "ebs_csi" {
  name = "${var.name}-ebs-csi"
  assume_role_policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = module.eks.oidc_provider_arn }
      Condition = { StringEquals = {
        "${local.dns_oidc_issuer}:sub" = "system:serviceaccount:kube-system:ebs-csi-controller-sa"
        "${local.dns_oidc_issuer}:aud" = "sts.amazonaws.com"
      } }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ebs_csi" {
  role       = aws_iam_role.ebs_csi.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

resource "aws_eks_addon" "ebs_csi" {
  cluster_name                = module.eks.cluster_name
  addon_name                  = "aws-ebs-csi-driver"
  addon_version               = var.ebs_csi_version
  service_account_role_arn    = aws_iam_role.ebs_csi.arn
  resolve_conflicts_on_create = "NONE"
  resolve_conflicts_on_update = "NONE"
  configuration_values        = jsonencode({ controller = { nodeSelector = { "astra/tier" = "cpu" } } })
  depends_on                  = [module.eks.eks_managed_node_groups, aws_iam_role_policy_attachment.ebs_csi]
}

output "ebs_csi_version" { value = aws_eks_addon.ebs_csi.addon_version }
