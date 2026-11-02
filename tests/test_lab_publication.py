import copy
import unittest
from datetime import datetime, timezone
from publish_lab_model import FILE_CHECKS, check_validation


class LabPublicationTests(unittest.TestCase):
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
