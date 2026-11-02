import copy
import hashlib
import json
import unittest
from datetime import datetime, timezone
from publish_lab_model import FILE_CHECKS, check_validation, publish
from pipeline_artifacts import canonical_json
from tests import test_promotion


class LabPublicationTests(unittest.TestCase):
    def publication_fixture(self):
        fixture = test_promotion.PromotionTests()
        fixture.setUp()
        fixture.evidence.update(passed=True, valid_until='2099-01-01T00:00:00Z')
        fixture.evidence['checks'] = dict.fromkeys(FILE_CHECKS, 'PASS')
        raw = canonical_json(fixture.evidence)
        key = 'pipeline/run/validation.json'
        fixture.s3.objects['evidence', key, 'validated'] = raw
        reference = {'uri': 's3://evidence/' + key, 'version': 'validated', 'sha256': hashlib.sha256(raw).hexdigest()}
        settings = {'evidence_bucket': 'evidence', 'quarantine_bucket': 'quarantine', 'release_bucket': 'releases'}
        return fixture, reference, settings

    def test_parallel_copy_preserves_scope_and_versions(self):
        fixture, reference, settings = self.publication_fixture()
        result = publish(fixture.s3, reference, settings, fixture.runtime)
        key = 'releases/release-1/release-manifest.json'
        manifest = json.loads(fixture.s3.objects['releases', key, result['version']])
        self.assertEqual(fixture.s3.writes[-1], key)
        self.assertEqual(manifest['publication']['separate_gpu_evaluation'], 'not_run')
        self.assertEqual(manifest['publication']['live_inference'], 'pending')
        self.assertTrue(all(item['version_id'] != 'source-version' for item in manifest['files']))

    def test_a_corrupt_parallel_copy_cannot_publish_a_manifest(self):
        fixture, reference, settings = self.publication_fixture()
        fixture.s3.corrupt_copy = True
        with self.assertRaises(ValueError):
            publish(fixture.s3, reference, settings, fixture.runtime)
        self.assertFalse(any(key.endswith('release-manifest.json') for key in fixture.s3.writes))

    def test_infrastructure_scope_keeps_file_and_runtime_checks(self):
        image = 'example@sha256:' + 'a' * 64
        report = {'passed': True, 'checks': dict.fromkeys(FILE_CHECKS, 'PASS'),
                  'valid_until': '2026-11-02T23:47:00Z', 'runtime_image': image,
                  'subject': {'runtime_digest': 'sha256:' + 'a' * 64, 'manifest_sha256': 'b' * 64},
                  'candidate': {'sha256': 'b' * 64}}
        now = datetime(2026, 11, 2, 19, tzinfo=timezone.utc)
        check_validation(report, image, now)
        for check in FILE_CHECKS:
            bad = copy.deepcopy(report)
            bad['checks'][check] = 'FAIL'
            with self.assertRaises(ValueError):
                check_validation(bad, image, now)
        with self.assertRaises(ValueError):
            check_validation(report, image, datetime(2026, 11, 3, tzinfo=timezone.utc))
        with self.assertRaises(ValueError):
            check_validation(report, image + '0', now)
        bad = copy.deepcopy(report)
        bad['candidate']['sha256'] = 'c' * 64
        with self.assertRaises(ValueError):
            check_validation(bad, image, now)


if __name__ == '__main__':
    unittest.main()
