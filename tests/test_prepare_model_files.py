import unittest
from unittest.mock import Mock

from prepare_model_files import check_runtime, wait_for_checks


class FilePreparationTests(unittest.TestCase):
    def test_failed_and_stopped_checks_cannot_publish(self):
        for status in ('Failed', 'Stopping', 'Stopped'):
            client = Mock()
            client.describe_pipeline_execution.return_value = {'PipelineExecutionStatus': status}
            with self.assertRaises(RuntimeError):
                wait_for_checks(client, 'test-execution')

    def test_waits_for_success_without_starting_another_execution(self):
        client = Mock()
        client.describe_pipeline_execution.side_effect = [
            {'PipelineExecutionStatus': 'Executing'}, {'PipelineExecutionStatus': 'Succeeded'}]
        wait_for_checks(client, 'test-execution', sleep=Mock())
        client.start_pipeline_execution.assert_not_called()
        client.stop_pipeline_execution.assert_not_called()

    def test_timeout_stops_only_the_current_execution(self):
        client = Mock()
        client.describe_pipeline_execution.return_value = {'PipelineExecutionStatus': 'Executing'}
        with self.assertRaises(TimeoutError):
            wait_for_checks(client, 'test-execution', timeout=1, clock=Mock(side_effect=[0, 2]))
        client.stop_pipeline_execution.assert_called_once_with(PipelineExecutionArn='test-execution')

    def test_runtime_checks_reject_another_image_and_unresolved_findings(self):
        image = 'example@sha256:' + 'a' * 64
        scan = {'ArtifactName': image, 'ArtifactType': 'container_image', 'Results': [{}]}
        check_runtime(scan, image)
        with self.assertRaises(ValueError):
            check_runtime(scan, 'another@sha256:' + 'b' * 64)
        scan['Results'] = [{'Vulnerabilities': [{'Severity': 'HIGH'}]}]
        with self.assertRaises(ValueError):
            check_runtime(scan, image)


if __name__ == '__main__':
    unittest.main()
