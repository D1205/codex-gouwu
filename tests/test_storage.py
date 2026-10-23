import json
from pathlib import Path
import tempfile
import unittest

from mechanical_app.storage import execution_lease, read_json, safe_id, sha256, verify_artifacts, write_json


class StorageTests(unittest.TestCase):
    def test_invalid_write_does_not_replace_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result.json"
            write_json(path, {"status": "failed"})
            with self.assertRaises(ValueError):
                write_json(path, {"value": float("nan")})
            self.assertEqual(read_json(path), {"status": "failed"})

    def test_traversal_is_not_a_task_id(self):
        for value in ("../old", "C:/outside", "name/child", "", "x\\y"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                safe_id(value)

    def test_lease_serializes_writers(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with execution_lease(root):
                with self.assertRaises(RuntimeError):
                    with execution_lease(root):
                        self.fail("Two writers acquired the CAD lease")
            self.assertFalse((root / "cad.lock").exists())

    def test_tampered_or_external_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            revision = root / "revision"
            revision.mkdir()
            artifact = revision / "model.step"
            artifact.write_bytes(b"original")
            receipt = {"artifacts": [{"path": str(artifact), "size_bytes": 8, "sha256": sha256(artifact)}]}
            self.assertEqual(verify_artifacts(receipt, revision), [])
            artifact.write_bytes(b"tampered")
            self.assertTrue(verify_artifacts(receipt, revision))
            external = root / "outside.step"
            external.write_bytes(b"outside")
            receipt["artifacts"] = [{"path": str(external), "size_bytes": 7, "sha256": sha256(external)}]
            self.assertTrue(verify_artifacts(receipt, revision))


if __name__ == "__main__":
    unittest.main()
