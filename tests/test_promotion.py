import copy
import hashlib
import io
import json
import unittest
from datetime import datetime, timezone

from pipeline_artifacts import canonical_json, runtime_findings
from promote_release import promote
from release_gate import REQUIRED


class S3:
    def __init__(self):
        self.objects = {}
        self.writes = []
        self.corrupt_copy = False

    def get_object(self, Bucket, Key, VersionId):
        return {"Body": io.BytesIO(self.objects[Bucket, Key, VersionId])}

    def put_object(self, Bucket, Key, Body, **options):
        if options.get("IfNoneMatch") == "*" and any(b == Bucket and k == Key for b, k, _ in self.objects):
            raise ValueError("PreconditionFailed")
        version = str(len(self.objects) + 1)
        self.objects[Bucket, Key, version] = Body
        self.writes.append(Key)
        return {"VersionId": version}

    def copy_object(self, Bucket, Key, CopySource, **options):
        data = self.objects[CopySource["Bucket"], CopySource["Key"], CopySource["VersionId"]]
        return self.put_object(Bucket, Key, b"corrupted" if self.corrupt_copy else data)


class Registry:
    def __init__(self, package):
        self.package = package

    def describe_model_package(self, ModelPackageName):
        return copy.deepcopy(self.package)


class PromotionTests(unittest.TestCase):
    def setUp(self):
        self.s3 = S3()
        self.runtime = "example/runtime@sha256:" + "a" * 64
        self.candidate = {"schema": 1, "release_id": "release-1", "status": "quarantine_unapproved",
                          "bucket": "quarantine", "source_repository": "publisher/model",
                          "source_revision": "f" * 40, "license_label": "apache-2.0", "files": []}
        for name, data in [("config.json", b"{}"), ("model.safetensors", b"synthetic-test-data")]:
            key = "candidates/release-1/attempt/" + name
            self.s3.objects["quarantine", key, "source-version"] = data
            self.candidate["files"].append({"path": name, "key": key, "version_id": "source-version",
                                             "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        raw = canonical_json(self.candidate)
        self.s3.objects["quarantine", "candidate.json", "candidate-version"] = raw
        self.expected = {"release_id": "release-1", "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                         "runtime_digest": "sha256:" + "a" * 64, "evalset_sha256": "b" * 64,
                         "policy_sha256": "c" * 64}
        self.evidence = {"release_id": "release-1", "subject": {k: v for k, v in self.expected.items() if k != "release_id"},
                         "checks": {k: "PASS" for k in REQUIRED}, "runtime_image": self.runtime,
                         "registry_status": "Approved", "valid_until": "2026-11-01T00:00:00Z",
                         "candidate": {"uri": "s3://quarantine/candidate.json", "version": "candidate-version",
                                       "sha256": self.expected["manifest_sha256"]}}
        raw = canonical_json(self.evidence)
        self.s3.objects["evidence", "result.json", "evidence-version"] = raw
        self.package = {"ModelPackageStatus": "Completed", "ModelPackageGroupName": "astra",
                        "ModelApprovalStatus": "Approved", "CustomerMetadataProperties": {
                            **self.expected, "evidence_uri": "s3://evidence/result.json",
                            "evidence_version": "evidence-version", "evidence_sha256": hashlib.sha256(raw).hexdigest()}}

    def run_promotion(self):
        return promote(self.s3, Registry(self.package), "package-arn", "evidence", "quarantine",
                       "releases", "astra", datetime(2026, 10, 30, tzinfo=timezone.utc))

    def test_current_registry_approval_required_even_if_report_says_approved(self):
        self.package["ModelApprovalStatus"] = "PendingManualApproval"
        with self.assertRaisesRegex(ValueError, "Registry approval missing"):
            self.run_promotion()
        self.assertEqual(self.s3.writes, [])

    def test_bad_evidence_hash_stops_before_copy(self):
        self.package["CustomerMetadataProperties"]["evidence_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.run_promotion()
        self.assertEqual(self.s3.writes, [])

    def test_corrupted_copy_never_publishes_manifest(self):
        self.s3.corrupt_copy = True
        with self.assertRaisesRegex(ValueError, "expected size|integrity"):
            self.run_promotion()
        self.assertFalse(any(key.endswith("release-manifest.json") for key in self.s3.writes))

    def test_publish_pins_copied_versions_and_writes_manifest_last(self):
        result = self.run_promotion()
        self.assertEqual(self.s3.writes[-1], "releases/release-1/release-manifest.json")
        raw = self.s3.objects["releases", self.s3.writes[-1], result["version"]]
        self.assertEqual(hashlib.sha256(raw).hexdigest(), result["sha256"])
        manifest = json.loads(raw)
        for item in manifest["files"]:
            self.assertNotEqual(item["version_id"], "source-version")
        self.assertEqual(manifest["source_revision"], "f" * 40)

    def test_completed_release_cannot_be_replaced(self):
        self.run_promotion()
        with self.assertRaisesRegex(ValueError, "PreconditionFailed"):
            self.run_promotion()

    def test_other_evidence_bucket_is_not_trusted(self):
        self.package["CustomerMetadataProperties"]["evidence_uri"] = "s3://uploader/result.json"
        with self.assertRaisesRegex(ValueError, "untrusted"):
            self.run_promotion()

    def test_scan_retains_unfixed_critical_findings(self):
        finding = {"Severity": "CRITICAL", "VulnerabilityID": "example", "FixedVersion": ""}
        report = {"ArtifactName": self.runtime, "ArtifactType": "container_image",
                  "Results": [{"Vulnerabilities": [finding]}]}
        self.assertEqual(runtime_findings(report, self.runtime), [finding])
        with self.assertRaisesRegex(ValueError, "another image"):
            runtime_findings(report, "other@sha256:" + "b" * 64)

    def test_empty_scan_is_not_a_passing_scan(self):
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            runtime_findings({"ArtifactName": self.runtime, "ArtifactType": "container_image", "Results": []}, self.runtime)
