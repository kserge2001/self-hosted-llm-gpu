import unittest
from unittest.mock import Mock

from model_storage import copy_version


class ModelStorageTests(unittest.TestCase):
    def test_large_model_shard_preserves_source_version_and_covers_every_byte(self):
        s3 = Mock()
        s3.create_multipart_upload.return_value = {"UploadId": "this-copy"}
        s3.upload_part_copy.return_value = {"CopyPartResult": {"ETag": "part-etag"}}
        s3.complete_multipart_upload.return_value = {"VersionId": "published-version"}
        item = {"key": "candidate/outside.safetensors", "version_id": "reviewed-version",
                "bytes": 6007102112, "sha256": "a" * 64}
        result = copy_version(s3, "quarantine", "release", item, "releases/model/files/outside.safetensors")
        self.assertEqual(result["VersionId"], "published-version")
        offset = 0
        for call in s3.upload_part_copy.call_args_list:
            self.assertEqual(call.kwargs["CopySource"]["VersionId"], "reviewed-version")
            start, end = map(int, call.kwargs["CopySourceRange"].removeprefix("bytes=").split("-"))
            self.assertEqual(start, offset)
            self.assertLessEqual(end - start + 1, 5 * 1024 ** 3)
            offset = end + 1
        self.assertEqual(offset, item["bytes"])
        s3.copy_object.assert_not_called()
        s3.abort_multipart_upload.assert_not_called()

    def test_failed_part_aborts_only_this_upload_without_completing(self):
        s3 = Mock()
        s3.create_multipart_upload.return_value = {"UploadId": "failed-copy"}
        s3.upload_part_copy.side_effect = RuntimeError("copy failed")
        item = {"key": "candidate/shard", "version_id": "source-version",
                "bytes": 6007102112, "sha256": "b" * 64}
        with self.assertRaisesRegex(RuntimeError, "copy failed"):
            copy_version(s3, "quarantine", "release", item, "releases/model/files/shard")
        s3.abort_multipart_upload.assert_called_once_with(
            Bucket="release", Key="releases/model/files/shard", UploadId="failed-copy")
        s3.complete_multipart_upload.assert_not_called()
