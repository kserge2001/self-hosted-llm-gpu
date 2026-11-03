import unittest

from start_model_preparation import request_arguments


class ModelPreparationRequestTests(unittest.TestCase):
    def setUp(self):
        self.request = dict(release_id='astra-001', pipeline_version=1,
                            manifest_uri='s3://test-quarantine/candidates/001.json',
                            manifest_version='version-1', manifest_sha256='a' * 64)

    def test_retry_keeps_the_same_input_versions_and_idempotency_token(self):
        first = request_arguments('astra-001', self.request)
        self.assertEqual(first, request_arguments('astra-001', self.request))
        self.assertEqual(first['PipelineVersionId'], 1)
        self.assertEqual(len(first['PipelineParameters']), 4)
        changed = request_arguments('astra-001', dict(self.request, manifest_version='version-2'))
        self.assertNotEqual(first['ClientRequestToken'], changed['ClientRequestToken'])

    def test_missing_or_inconsistent_input_identity_is_rejected(self):
        for key, value in [('pipeline_version', 0), ('pipeline_version', True),
                           ('manifest_uri', 'https://example.org/model'), ('manifest_uri', []),
                           ('manifest_sha256', None), ('manifest_sha256', 'not-a-hash'),
                           ('manifest_version', 'null'), ('manifest_version', 4),
                           ('manifest_version', '   '), ('release_id', 'different')]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                request_arguments('astra-001', dict(self.request, **{key: value}))
        with self.assertRaises(ValueError):
            request_arguments('astra-001', dict(self.request, unexpected='value'))

    def test_names_match_the_aws_display_name_constraints(self):
        for name in ['a', 'astra-001', 'a' * 63]:
            self.assertEqual(request_arguments(name, dict(self.request, release_id=name))[
                'PipelineExecutionDisplayName'], name)
        for name in ['astra-', '../escape', '--option', 'a' * 64, 'Astra']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                request_arguments(name, dict(self.request, release_id=name))


if __name__ == '__main__':
    unittest.main()
