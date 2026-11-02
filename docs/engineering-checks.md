# Engineering reference

Use the [published Astra capstone](https://kodelumi.com/w/49_OMkQYNp9zuC57) for the student walkthrough and [validation status](validation-status.md) for what has actually been tested.

The required live checks are a real Astra response, the supplied assistants' tool calls, live GPU metrics in Grafana, prompt versions and request traces in MLflow, model files in S3, and cleanup. The target remains two replicas across two zones; the last rehearsal verified only one GPU because of capacity availability.

Repository checks verify code and configuration. They are supplied maintenance checks, not a student model-evaluation assignment. The previous benchmark questions, evaluation scoring and separate GPU evaluation are removed from the classroom implementation.
