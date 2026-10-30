# Open managed MLflow

SageMaker-managed MLflow uses AWS permissions. It has no separate MLflow username or password.

Use your configured AWS CLI to create a temporary sign-in link. Replace the tracking server name with your Terraform output, then open the returned URL in your browser.

```bash
aws sagemaker create-presigned-mlflow-tracking-server-url \
  --region us-east-1 \
  --tracking-server-name YOUR_TRACKING_SERVER_NAME \
  --query AuthorizedUrl --output text
```

The calling AWS identity must have permission to create the link and use the tracking server UI. Treat the returned URL as a temporary credential. The server must still exist and be running.

The custom MLflow domain currently uses the authenticated launcher. Changing that entry point is separate from opening the managed UI with AWS credentials.
