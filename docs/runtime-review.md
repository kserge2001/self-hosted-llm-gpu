# Approved, bounded runtime exception

The current repaired local image is `astra-runtime@sha256:88305bdd47854ad08ae8800b6c8309d198d5b6c2ff78b16108353faafab5ec67`. It is a candidate, not an approved release.

The November 1 scan refresh found four newly reported pyasn1 issues. Updating pyasn1 to 0.6.5 fixed them. The final report, `evidence/runtime-scan-repaired-2026-11-01.json`, has **385 remaining findings: 371 HIGH and 14 CRITICAL**, all against linux-libc-dev and all included in the official-record review below. No other HIGH/CRITICAL findings remain in that report. The owner explicitly approved the documented exception during the November 1 voice conversation.

The preceding October 30 image's Trivy 0.76.1 report had 386 HIGH/CRITICAL findings, all against the installed `linux-libc-dev` 6.8.0-147.147 package. Its unmodified report is retained at `evidence/runtime-scan-repaired-v2.json`. The November 1 header set is a subset of that reviewed set.

The applicability review retrieved all 386 official CVE records from the CVE Program's cvelistV5 repository. Each record identifies Linux kernel code. The retrieved JSON and source hashes are retained in `evidence/header-review/`; the container package/file inventory is `evidence/runtime-header-inventory.json`. `/boot` and `/lib/modules` contain no kernel binaries or modules in this image.

385 records identify no UAPI file. CVE-2026-80668 also lists `include/uapi/linux/netfilter/nf_conntrack_common.h`; its documented defect is a race in kernel conntrack expectation garbage collection. The image includes userspace definitions, not the kernel conntrack implementation. The relevant header and official description were inspected and retained. See the [official CVE record](https://github.com/CVEProject/cvelistV5/blob/main/cves/2026/80xxx/CVE-2026-80668.json).

This is a container applicability assessment. It does not assess the kernel of an EKS worker, SageMaker host or Docker host. The headers remain installed because the runtime may need them for compilation; their package records and scan findings have not been removed or hidden.

The recorded exception binds to this exact image digest, package version and enumerated CVE list. It preserves the raw scan and review evidence and rejects every other HIGH/CRITICAL finding. The approved record is retained in `evidence/runtime-exception-approved.json` and expires November 1 at 22:45 UTC. The validator accepts exceptions only from a pinned version/hash in the trusted evidence bucket. Tests reject absent approval, another image, changed package versions, wildcard entries, unreviewed CVEs and expiry. New findings or a different image require a new review; expiry is enforced rather than silently extended.

Approval of this exception is not model-release approval or proof of working inference. The file checks and a real serving request are still required for the classroom path.

The local runtime also still needs a real GPU serving check. A completed build, dependency check or applicability review cannot establish successful inference.
