variable "mlflow_server_version" {
  description = "Optional AWS-supported server version. Record the resolved version from the mlflow output."
  type        = string
  default     = null
}

resource "aws_iam_role" "mlflow" {
  name = "${var.name}-mlflow"
  assume_role_policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect    = "Allow", Action = "sts:AssumeRole"
      Principal = { Service = "sagemaker.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "mlflow" {
  name = "mlflow-artifact-store"
  role = aws_iam_role.mlflow.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:ListBucket", "s3:GetBucketLocation"], Resource = aws_s3_bucket.data["mlflow"].arn },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:AbortMultipartUpload"], Resource = "${aws_s3_bucket.data["mlflow"].arn}/*" },
    { Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"], Resource = aws_kms_key.platform.arn }
  ] })
}

resource "aws_sagemaker_mlflow_tracking_server" "astra" {
  tracking_server_name         = "${var.name}-mlflow"
  artifact_store_uri           = "s3://${aws_s3_bucket.data["mlflow"].id}/artifacts"
  role_arn                     = aws_iam_role.mlflow.arn
  mlflow_version               = var.mlflow_server_version
  tracking_server_size         = "Small"
  automatic_model_registration = false
  depends_on                   = [aws_iam_role_policy.mlflow, aws_s3_bucket_server_side_encryption_configuration.data]
}

output "mlflow" {
  value = {
    name    = aws_sagemaker_mlflow_tracking_server.astra.tracking_server_name
    version = aws_sagemaker_mlflow_tracking_server.astra.mlflow_version
    arn     = aws_sagemaker_mlflow_tracking_server.astra.arn
  }
}
