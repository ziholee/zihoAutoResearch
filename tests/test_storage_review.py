"""Independent checks for failure cleanup before the atomic commit point."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from zar.storage import atomic_write, project_lock


class StorageReviewTests(unittest.TestCase):
    def test_fsync_failure_preserves_original_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical = root / "project.json"
            canonical.write_text("unchanged")
            with patch("zar.storage.os.fsync", side_effect=OSError("simulated flush failure")):
                with self.assertRaises(OSError):
                    atomic_write(canonical, "new content")
            self.assertEqual(canonical.read_text(), "unchanged")
            self.assertEqual(list(root.iterdir()), [canonical])

    def test_exception_inside_lock_releases_only_acquired_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "operation failed"):
                with project_lock(root):
                    raise RuntimeError("operation failed")
            self.assertFalse((root / ".lock").exists())
            with project_lock(root):
                self.assertTrue((root / ".lock").exists())
