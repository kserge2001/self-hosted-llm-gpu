# Supplied model preparation

The [Model Preparation lesson in Kodelumi](https://kodelumi.com/w/49_OMkQYNp9zuC57) is the student guide. It explains the flow with a diagram and a short reference note. Students do not build a pipeline or run model-evaluation questions.

The provided `prepare_model_files.py` helper runs CPU file checks after the download/upload demo. It reuses the validation implementation and saves the exact validation reference for `publish_lab_model.py`. The prepared release is tested by making a real request after EKS serving starts.

The automated checks cover publisher/revision, license metadata, file completeness and hashes, safetensors format, exact-version malware results and the runtime container scan. These are artifact checks, not model-quality scores. The helper starts no GPU evaluation. It saves its execution so a retry can reconnect to the same attempt, and stops that execution if its wait times out or the user interrupts it.

The previous question suite and GPU evaluation implementation have been removed. Infrastructure resources and the two-zone serving design are unchanged. Historical evaluation/release records remain historical evidence, not current classroom requirements.
