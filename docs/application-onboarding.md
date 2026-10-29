# Application Onboarding

## Connect an application to Astra

Provide this guide to the application team after you have verified the endpoint. Complete the hostname, access process, request limits and support contact with the values from your deployed platform.

Applications call Astra through LiteLLM's HTTPS endpoint. The model name is **astra**. The ALB is internet-facing so local code can reach it from an allowed public IP. vLLM remains private behind the gateway.

**Connection details to provide**

- **Base URL:** https://YOUR_ASTRA_HOST/v1. Replace YOUR_ASTRA_HOST with your deployed DNS hostname.
- **Model:** astra.
- **Access:** a separate application key issued by the platform team. Set its model permission, budget and request limits. Supply it through the approved secret store.
- **Network:** add the developer's current public IP, or the application's approved egress address, to public_client_cidrs in Terraform. The Gateway's ALB uses that allowlist.
- **Limits:** provide the verified input/output token limits, request-rate limit and timeout. Publish measured limits after validation.
- **Support:** provide the service owner and incident contact.

Use an application key in client code. Keep the gateway master key with platform administrators. Keep keys out of Git, screenshots, browser frontend code and logs.

## Make the first request from your laptop

Use the same OpenAI Python SDK as before. Replace YOUR_ASTRA_HOST with your deployed hostname, run this code in your prepared Python environment and enter your application key when prompted.

```python
from getpass import getpass
from openai import OpenAI

client = OpenAI(
    base_url="https://YOUR_ASTRA_HOST/v1",
    api_key=getpass("Astra application key: "),
)

response = client.chat.completions.create(
    model="astra",
    messages=[{"role": "user", "content": "Explain a Kubernetes Service in two sentences."}],
    max_tokens=160,
)

print(response.choices[0].message.content)
```

**Expected result:** Astra's answer appears below the code. The request goes to your LiteLLM gateway through the base URL you supplied.

## Handle errors and tool calls

- **401 or 403:** check the application's key, revocation status and permission to use astra. Request a replacement through the access process.
- **429:** follow the gateway's rate or budget policy. Use bounded retries only for temporary rate limits; an exhausted budget requires a policy decision.
- **Connection timeout:** check the public-IP allowlist, DNS and ALB health.
- **Certificate error:** check that the hostname matches the wildcard certificate and that its chain is trusted. Keep certificate verification enabled.
- **400:** inspect the request format, model name and token limits.
- **5xx:** record the request ID and contact the platform owner. Use bounded retry behavior appropriate to your application.

A tool call is a request from the model to your application. Your application validates the tool name and arguments, performs the approved operation with its own Kubernetes or AWS identity, then sends the tool result back to Astra. A tool call does not grant infrastructure permissions. Implement that loop using Assistant Integration.

## Complete the application handover

Run the Python Chat Completions example with the application's own key. Confirm its usage appears under the correct application in LiteLLM. Complete the application trace check in Platform Verification. Provide the filled connection details, working example, limits and support contact to the application team.

Revoke an exercise-only key through the platform's key-management process when you finish.
