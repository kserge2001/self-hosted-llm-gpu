import copy
import hashlib
import io
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from publish_lab_model import FILE_CHECKS, check_validation, publish
from pipeline_artifacts import canonical_json, runtime_findings


class Storage:
    def __init__(self):
        self.objects = {}
        self.writes = []
        self.corrupt_copy = False

    def get_object(self, Bucket, Key, VersionId):
        return {'Body': io.BytesIO(self.objects[Bucket, Key, VersionId])}

    def put_object(self, Bucket, Key, Body, **options):
        if options.get('IfNoneMatch') == '*' and any(b == Bucket and k == Key for b, k, _ in self.objects):
            raise ValueError('PreconditionFailed')
        version = str(len(self.objects) + 1)
        self.objects[Bucket, Key, version] = Body
        self.writes.append(Key)
        return {'VersionId': version}

    def copy_object(self, Bucket, Key, CopySource, **options):
        data = self.objects[CopySource['Bucket'], CopySource['Key'], CopySource['VersionId']]
        return self.put_object(Bucket, Key, b'corrupted' if self.corrupt_copy else data)


class LabPublicationTests(unittest.TestCase):
    def publication_fixture(self):
        fixture = SimpleNamespace(s3=Storage(), runtime='example/runtime@sha256:' + 'a' * 64)
        candidate = {'schema': 1, 'release_id': 'release-1', 'status': 'quarantine_unapproved',
                     'bucket': 'quarantine', 'source_repository': 'publisher/model',
                     'source_revision': 'f' * 40, 'license_label': 'apache-2.0', 'files': []}
        for name, data in [('config.json', b'{}'), ('model.safetensors', b'unit-test-bytes')]:
            key = 'candidates/release-1/attempt/' + name
            fixture.s3.objects['quarantine', key, 'source-version'] = data
            candidate['files'].append({'path': name, 'key': key, 'version_id': 'source-version',
                                       'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        raw = canonical_json(candidate)
        fixture.s3.objects['quarantine', 'candidate.json', 'candidate-version'] = raw
        candidate_hash = hashlib.sha256(raw).hexdigest()
        fixture.evidence = {
            'release_id': 'release-1', 'runtime_image': fixture.runtime, 'passed': True,
            'valid_until': '2099-01-01T00:00:00Z', 'checks': dict.fromkeys(FILE_CHECKS, 'PASS'),
            'subject': {'runtime_digest': 'sha256:' + 'a' * 64, 'manifest_sha256': candidate_hash,
                        'policy_sha256': 'c' * 64},
            'candidate': {'uri': 's3://quarantine/candidate.json', 'version': 'candidate-version',
                          'sha256': candidate_hash},
        }
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
        self.assertEqual(manifest['publication']['scope'], 'infrastructure_lab')
        self.assertEqual(manifest['publication']['live_inference'], 'pending')
        self.assertTrue(all(item['version_id'] != 'source-version' for item in manifest['files']))

    def test_a_corrupt_parallel_copy_cannot_publish_a_manifest(self):
        fixture, reference, settings = self.publication_fixture()
        fixture.s3.corrupt_copy = True
        with self.assertRaises(ValueError):
            publish(fixture.s3, reference, settings, fixture.runtime)
        self.assertFalse(any(key.endswith('release-manifest.json') for key in fixture.s3.writes))

    def test_a_completed_release_cannot_be_overwritten(self):
        fixture, reference, settings = self.publication_fixture()
        publish(fixture.s3, reference, settings, fixture.runtime)
        with self.assertRaisesRegex(ValueError, 'PreconditionFailed'):
            publish(fixture.s3, reference, settings, fixture.runtime)

    def test_untrusted_or_corrupted_validation_cannot_start_copying(self):
        fixture, reference, settings = self.publication_fixture()
        for changed in (dict(reference, uri='s3://uploader/pipeline/run/validation.json'),
                        dict(reference, sha256='0' * 64)):
            with self.assertRaises(ValueError):
                publish(fixture.s3, changed, settings, fixture.runtime)
        self.assertEqual(fixture.s3.writes, [])

    def test_scanning_keeps_unfixed_findings_and_rejects_empty_reports(self):
        image = 'example/runtime@sha256:' + 'a' * 64
        finding = {'Severity': 'CRITICAL', 'VulnerabilityID': 'unit-test', 'FixedVersion': ''}
        report = {'ArtifactName': image, 'ArtifactType': 'container_image',
                  'Results': [{'Vulnerabilities': [finding]}]}
        self.assertEqual(runtime_findings(report, image), [finding])
        report['Results'] = []
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            runtime_findings(report, image)

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
