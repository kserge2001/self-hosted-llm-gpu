import copy
import unittest

from scan_gate import check_scans


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {"bucket": "quarantine", "files": [{"path": "model.safetensors", "key": "candidate/model.safetensors", "version_id": "v1"}]}
        self.event = {"source": "aws.guardduty", "detail-type": "GuardDuty Malware Protection Object Scan Result",
                      "account": "123", "resources": ["plan-arn"], "id": "event-1", "detail": {
                          "scanStatus": "COMPLETED", "scanResultDetails": {"scanResultStatus": "NO_THREATS_FOUND"},
                          "s3ObjectDetails": {"bucketName": "quarantine", "objectKey": "candidate/model.safetensors", "versionId": "v1"}}}

    def test_requires_exact_version(self):
        self.event["detail"]["s3ObjectDetails"]["versionId"] = "older"
        with self.assertRaisesRegex(ValueError, "Missing"):
            check_scans(self.manifest, [self.event], "123", "plan-arn")

    def test_wrong_plan_cannot_supply_evidence(self):
        with self.assertRaisesRegex(ValueError, "Missing"):
            check_scans(self.manifest, [self.event], "123", "another-plan")

    def test_conflicting_or_skipped_scan_blocks_release(self):
        bad = copy.deepcopy(self.event)
        bad["detail"]["scanStatus"] = "SKIPPED"
        with self.assertRaisesRegex(ValueError, "failed, skipped"):
            check_scans(self.manifest, [self.event, bad], "123", "plan-arn")

    def test_valid_event_records_its_identity(self):
        evidence = check_scans(self.manifest, [self.event], "123", "plan-arn")
        self.assertEqual(evidence[0]["event_ids"], ["event-1"])
