"""Apply an explicit, expiring owner-approved exception to enumerated findings."""

import re
from datetime import datetime, timezone


def apply_exception(findings, exception, runtime_image, now=None):
    now = now or datetime.now(timezone.utc)
    if (exception.get("schema") != 1 or exception.get("status") != "owner_approved"
            or not exception.get("approval_record") or not exception.get("reason")):
        raise ValueError("Runtime exception has no recorded owner approval")
    if exception.get("runtime_digest") != runtime_image.rsplit("@", 1)[-1]:
        raise ValueError("Runtime exception belongs to another image")
    expires = datetime.fromisoformat(exception["valid_until"].replace("Z", "+00:00"))
    begins = datetime.fromisoformat(exception["approved_at"].replace("Z", "+00:00"))
    if (expires.tzinfo is None or begins.tzinfo is None or not begins <= now < expires
            or (expires - begins).total_seconds() > 24 * 3600):
        raise ValueError("Runtime exception is expired, future-dated or exceeds one day")
    entries = exception.get("findings")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Runtime exception needs an explicit finding list")
    approved = set()
    for item in entries:
        if (item.get("package") != "linux-libc-dev" or not item.get("version")
                or not re.fullmatch(r"CVE-[0-9]{4}-[0-9]+", item.get("id", ""))
                or not re.fullmatch(r"[a-f0-9]{64}", item.get("review_sha256", ""))):
            raise ValueError("Only individually reviewed kernel-header findings are allowed")
        approved.add((item["package"], item["version"], item["id"]))
    accepted, blocked = [], []
    for finding in findings:
        identity = (finding.get("PkgName"), finding.get("InstalledVersion"), finding.get("VulnerabilityID"))
        (accepted if identity in approved else blocked).append(finding)
    return blocked, accepted
