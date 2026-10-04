import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zar.storage import atomic_write, project_lock


class StorageTests(unittest.TestCase):
    def test_replace_failure_preserves_original_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'project.json'
            path.write_text('original')
            with patch('zar.storage.os.replace', side_effect=OSError('disk error')):
                with self.assertRaises(OSError):
                    atomic_write(path, 'replacement')
            self.assertEqual(path.read_text(), 'original')
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_lock_conflict_does_not_remove_existing_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with project_lock(root):
                with self.assertRaises(FileExistsError):
                    with project_lock(root):
                        self.fail('acquired twice')
                self.assertTrue((root / '.lock').exists())
            self.assertFalse((root / '.lock').exists())
