import hashlib
import tempfile
import unittest
from pathlib import Path

from migrate import migration_digests


class MigrationDigestTests(unittest.TestCase):
    def write(self, data):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "m.sql"
        path.write_bytes(data)
        return path

    def test_lf_and_crlf_checkouts_record_the_same_digest(self):
        lf, _ = migration_digests(self.write(b"SELECT 1;\nSELECT 2;\n"))
        crlf, _ = migration_digests(self.write(b"SELECT 1;\r\nSELECT 2;\r\n"))
        self.assertEqual(lf, crlf)

    def test_hash_recorded_from_a_crlf_checkout_still_counts_as_applied(self):
        old = hashlib.sha256(b"SELECT 1;\r\n").hexdigest()
        _, accepted = migration_digests(self.write(b"SELECT 1;\n"))
        self.assertIn(old, accepted)

    def test_real_content_change_is_still_detected(self):
        old = hashlib.sha256(b"SELECT 1;\n").hexdigest()
        _, accepted = migration_digests(self.write(b"SELECT 2;\n"))
        self.assertNotIn(old, accepted)
