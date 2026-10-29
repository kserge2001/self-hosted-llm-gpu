# Platform Verification

## Open the platform

Use the browser addresses created from your domain in AWS Foundation. Sign in with your approved dashboard account. Start this walkthrough after the gateway, assistants and monitoring have been deployed.

For the CareCart example, the addresses are:

- **LiteLLM:** https://litellm.afriqhome.com
- **Argo CD:** https://argocd.afriqhome.com
- **MLflow:** https://mlflow.afriqhome.com
- **Grafana:** https://grafana.afriqhome.com
- **Kubernetes assistant:** https://k8sassistant.afriqhome.com
- **AWS assistant:** https://awsassistant.afriqhome.com

Use your configured domain and subdomains for your own deployment. These are the intended addresses, not a statement that the services are currently available.

Keep these pages open as you follow one request through the platform. Save a screenshot or short note for each result. Keep keys and temporary sign-in links out of screenshots.

## Check the deployment in Argo CD

Open each deployed Astra application. Check that it is **Synced** and **Healthy** and that its Git revision matches the change you approved. Expand the application resources and check that both vLLM pods and both LiteLLM pods are Ready.

In the AWS EKS console, open the cluster's Compute view. Confirm that its CPU and GPU workers are present in the two selected Availability Zones.

**Expected result:** the reviewed configuration is deployed and the required replicas are running. A green deployment alone does not prove the model can answer; check that next.

## Send a request and find it in LiteLLM

Run the short OpenAI Chat Completions example from Application Onboarding with your application's own key. Then open LiteLLM and find that application's usage. Refresh the view if the usage record has not appeared yet.

Check the model name, token usage and the application or team that owns the request. Open its key settings and review the allowed model, rate limit and budget. Do not reveal or copy the gateway master key.

**Expected result:** Astra returns an answer and LiteLLM attributes the usage to the correct application. LiteLLM's usage cost is application accounting; review actual infrastructure charges in AWS Billing.

## Follow an assistant request in MLflow

Open the Kubernetes assistant and ask it to explain a synthetic Pending pod in its permitted namespace. Open MLflow, sign in and follow the redirect to the managed UI. Find the new assistant trace.

Open the model call, tool call, tool result and final answer. Confirm that the answer reflects the returned tool data. Open the prompt's numeric version and the evaluation run linked to the model release. Inspect the recorded scores, individual results and permitted artifacts. Add feedback to the trace using the configured reviewer access.

Repeat with the AWS assistant using a read-only infrastructure question. Confirm that it has its own trace and application usage record.

**Expected result:** you can follow a real request, identify the prompt and model release it used, and inspect the evaluation evidence. A synthetic demonstration trace is not the request you just made. If a required view or record is missing, leave that check unfinished and fix the integration.

## Observe the GPU and service health

Open Grafana and select a recent time range. Send a few short requests through Astra. Watch GPU utilization, GPU memory, ready replicas, request volume, errors and response time. Check that the dashboards contain current data from both GPU workers.

In the AWS console, open CloudWatch for the cluster and managed services. Check their recent health metrics and logs. Open RDS and ElastiCache to confirm the database and cache are available and have the configured Multi-AZ setup.

**Expected result:** the dashboards show live measurements. GPU utilization can fall between short requests; a quiet graph is not by itself a fault. Empty or stale graphs need investigation.

## Record the result and move to recovery

Record the deployed Git revision, model release, successful application request and MLflow trace. Note any missing page, unhealthy resource or failed request and fix it before handing over the service.

This walkthrough demonstrates the running platform. Use the checks in each build step to verify permissions and release controls; opening a dashboard alone does not prove those controls work. The detailed engineering checks remain in the repository for deeper validation.

Continue to Troubleshooting and Recovery to practise finding and fixing a failure. Complete Cleanup when the exercise is finished.
