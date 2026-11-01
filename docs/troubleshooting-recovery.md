# Troubleshooting and Recovery

Use this reference when a build step or request fails. Correct the cause, then repeat that step. Keep authentication and the existing infrastructure design in place.

## A. Find where the request stops

Follow the path: client URL and key, DNS and TLS, ALB target health, LiteLLM, model readiness, then the model response.

```bash
kubectl -n platform-system get gateway astra-public
kubectl -n gateway get httproute astra-inference
kubectl -n gateway get pods -l app=litellm -o wide
kubectl -n gateway get endpointslices -l kubernetes.io/service-name=litellm
kubectl -n llm get pods -l app=vllm -o wide
kubectl -n llm get endpointslices -l kubernetes.io/service-name=vllm
```

The Gateway should be Programmed, the route Accepted, and both Services should have ready endpoints. For an unready pod, inspect that pod's events and relevant container log. Save the error and status without credentials or sensitive prompt content.

## B. Resolve common failures

- **Cluster connection timeout:** check the approved private route, DNS and operator identity.
- **HTTP 401 or 403:** check the application key and allowed model. Issue a replacement through the gateway administration process if needed.
- **HTTP 429:** check the application's configured rate limit or budget.
- **Loader failure:** compare the manifest version and hash with the approved release. Correct the configuration and recreate the failed pod with an empty model volume.
- **Model pod Pending:** check GPU quota, zone capacity, node readiness, device-plugin status and the GPU request or toleration.
- **Gateway cannot reach its stores:** check the synchronized secret, private endpoints, TLS settings and database initialization.
- **Assistant tool denied:** check the requested namespace or action against the tool's existing role. Use the permitted synthetic namespace.
- **Missing trace or metric:** check the workload identity, tracking configuration, exporter and scrape target. A trace ID or dashboard alone does not prove data arrived.

## C. Confirm the correction

Repeat the failed request and check its result in the application, LiteLLM and the relevant trace or metric. If a deployment change caused the problem, restore the saved, reviewed configuration in Git and synchronize it through Argo CD.

Record the cause and correction so the next person can follow the working instructions. The separate engineering reference contains deeper recovery exercises for later operational work.
