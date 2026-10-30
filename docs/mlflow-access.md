# Open MLflow from the AWS console

Use your approved AWS account in us-east-1. You need SageMaker Studio access and permission to open the managed MLflow tracking server.

1. Open Amazon SageMaker AI in the AWS console.
2. Open Studio using your user profile.
3. In Studio, choose Applications, then MLflow.
4. Find your tracking server in MLflow Tracking Servers. Start it if its status is Off.
5. Open its three-dot menu and choose Open MLflow.
6. In the managed MLflow page, inspect your experiments, prompt versions and traces.

AWS opens the managed UI in a new tab. There is no custom MLflow hostname, Kubernetes launcher or Cognito login in this path.

The starter creates the tracking server, but does not provision SageMaker Studio user access. Arrange that access before this walkthrough. The console steps are verified against [AWS documentation](https://docs.aws.amazon.com/sagemaker/latest/dg/mlflow-launch-ui.html); they were not exercised in the temporary test account.
