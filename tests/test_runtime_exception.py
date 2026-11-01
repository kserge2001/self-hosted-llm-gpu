import copy
import unittest
from datetime import datetime, timezone

from runtime_exception import apply_exception


class RuntimeExceptionTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 1, 17, tzinfo=timezone.utc)
        self.image = "example/runtime@sha256:" + "a" * 64
        self.finding = {"PkgName": "linux-libc-dev", "InstalledVersion": "6.8.0-147.147",
                        "VulnerabilityID": "CVE-2026-63825", "Severity": "HIGH"}
        self.exception = {"schema": 1, "status": "owner_approved", "approval_record": "explicit test owner approval",
            "reason": "Reviewed kernel implementation absent from container", "runtime_digest": "sha256:" + "a" * 64,
            "approved_at": "2026-11-01T16:43:00Z", "valid_until": "2026-11-01T22:43:00Z",
            "findings": [{"package": "linux-libc-dev", "version": "6.8.0-147.147", "id": "CVE-2026-63825", "review_sha256": "b" * 64}]}

    def test_only_exact_reviewed_finding_is_accepted(self):
        other = dict(self.finding, VulnerabilityID="CVE-2026-999999")
        blocked, accepted = apply_exception([self.finding, other], self.exception, self.image, self.now)
        self.assertEqual(blocked, [other])
        self.assertEqual(accepted, [self.finding])

    def test_other_package_or_version_stays_blocked(self):
        for changes in [{"PkgName": "pyasn1"}, {"InstalledVersion": "other"}]:
            finding = dict(self.finding, **changes)
            self.assertEqual(apply_exception([finding], self.exception, self.image, self.now), ([finding], []))

    def test_expired_or_other_image_exception_rejected(self):
        with self.assertRaisesRegex(ValueError, "another image"):
            apply_exception([self.finding], self.exception, "example/runtime@sha256:" + "c" * 64, self.now)
        self.exception["valid_until"] = "2026-11-01T16:44:00Z"
        with self.assertRaisesRegex(ValueError, "expired"):
            apply_exception([self.finding], self.exception, self.image, self.now)

    def test_no_owner_approval_and_broad_exceptions_rejected(self):
        for change in ["unapproved", "wrong-package", "wildcard"]:
            exception = copy.deepcopy(self.exception)
            if change == "unapproved":
                exception["status"] = "proposed"
            elif change == "wrong-package":
                exception["findings"][0]["package"] = "pyasn1"
            else:
                exception["findings"][0]["id"] = "*"
            with self.assertRaises(ValueError):
                apply_exception([self.finding], exception, self.image, self.now)


if __name__ == "__main__":
    unittest.main()
