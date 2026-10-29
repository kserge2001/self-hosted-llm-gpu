import io
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quarantine_intake import download, selected_files


class IntakeTests(unittest.TestCase):
    def test_changed_download_is_rejected_before_upload(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("quarantine_intake.urlopen", return_value=io.BytesIO(b"bad")):
                with self.assertRaisesRegex(ValueError, "hash"):
                    download("https://huggingface.co/test", Path(folder)/"file",
                             hashlib.sha256(b"good").hexdigest(), 3)

    def test_oversized_download_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("quarantine_intake.urlopen", return_value=io.BytesIO(b"too big")):
                with self.assertRaisesRegex(ValueError, "size"):
                    download("https://huggingface.co/test", Path(folder)/"file", expected_bytes=2)

    def test_python_and_pickle_are_excluded(self):
        candidate = {"source_repository": "publisher/model", "source_revision": "a"*40,
                     "inventory": ["model.safetensors", "config.json", "model.py", "weights.pkl"],
                     "weights": [{"path": "model.safetensors", "reported_sha256": "b"*64, "reported_bytes": 100}]}
        names, _ = selected_files(candidate)
        self.assertEqual(names, ["model.safetensors", "config.json"])
        candidate["weights"][0]["reported_sha256"] = None
        with self.assertRaisesRegex(ValueError, "publisher hash"):
            selected_files(candidate)

    def test_executable_cannot_be_disguised_as_a_weight(self):
        candidate = {"source_repository": "publisher/model", "source_revision": "a"*40,
                     "inventory": ["model.py"],
                     "weights": [{"path": "model.py", "reported_sha256": "b"*64, "reported_bytes": 100}]}
        with self.assertRaises(ValueError):
            selected_files(candidate)
