import json
import unittest
import yaml
from prepare_model_pipeline import intake_yaml, request_from_log


class PreparationTests(unittest.TestCase):
    def test_intake_connects_the_candidate_and_workload_identity(self):
        text = intake_yaml({'model_scanning': {'intake_role_arn': 'arn:test:intake'},
                            'buckets': {'quarantine': 'test-quarantine'}},
                           {'intake': {'image': 'example@sha256:' + 'a' * 64}},
                           {'source_repository': 'Qwen/test'}, 'class-001')
        documents = {doc['kind']: doc for doc in yaml.safe_load_all(text)}
        pod = documents['Job']['spec']['template']['spec']
        self.assertEqual(pod['volumes'][0]['configMap']['name'], documents['ConfigMap']['metadata']['name'])
        self.assertEqual(pod['serviceAccountName'], documents['ServiceAccount']['metadata']['name'])
        self.assertEqual(json.loads(documents['ConfigMap']['data']['astra-candidate.json'])['source_repository'], 'Qwen/test')
        self.assertNotIn('${', text)

    def test_only_a_completed_intake_reference_can_create_a_request(self):
        reference = {'manifest_uri': 's3://test/candidate.json', 'manifest_version': 'v1', 'manifest_sha256': 'a' * 64}
        value = request_from_log('class-001', 'Uploaded files\n' + json.dumps(reference), {'pipeline_version': 3})
        self.assertEqual(value['manifest_version'], 'v1')
        self.assertEqual(value['pipeline_version'], 3)
        for log in ('', 'Download failed', json.dumps(dict(reference, manifest_version='null'))):
            with self.assertRaises(ValueError):
                request_from_log('class-001', log, {'pipeline_version': 3})


if __name__ == '__main__':
    unittest.main()
