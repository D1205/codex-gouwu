"""Application-boundary tests. The fake is never used as a CAD qualification."""
import copy
from pathlib import Path
import tempfile
import unittest

from mechanical_app.rules import LOCKED_SKILL_SHA256
from mechanical_app.service import DesignService, RevisionConflict, required_check_ids
from mechanical_app.storage import sha256


def task():
    dimensions = dict(length=80.0, width=50.0, height=4.0, hole_diameter=5.0, hole_margin=10.0)
    return dict(schema_version="engineering-task/1", task_id="service-test", revision=1,
                action="create", family="plate", goal="Application-boundary fixture", scope="geometry_review",
                sources=[dict(id="user-1", kind="user", reference="Explicit fixture dimensions")],
                parameters={key: dict(value=value, unit="mm", source_id="user-1", confirmed=True) for key, value in dimensions.items()},
                hard_constraints={"length": 80.0}, baseline=None, deliverables=["native"], tolerance_mm=0.01,
                rule_set_version="engineering-rules/1", skill_sha256=LOCKED_SKILL_SHA256)


def receipt_fake(plan, output, **kwargs):
    """Fake receipt for state tests only; deliberately not a real CAD file."""
    artifact = output / "state-test-only.sldprt"
    artifact.write_bytes(b"UNIT TEST ONLY: NOT A CAD ARTIFACT")
    return dict(status="passed", task_id=plan["task_id"], revision=plan["revision"], semantic_hash=plan["semantic_hash"],
                checks=[dict(id=key, status="passed", actual=True, expected=True) for key in required_check_ids(plan)],
                artifacts=[dict(kind="native", path=str(artifact), size_bytes=artifact.stat().st_size, sha256=sha256(artifact))])


class ServiceTests(unittest.TestCase):
    def test_failed_execution_does_not_publish_a_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            def failed(*args, **kwargs):
                raise RuntimeError("Injected worker failure")
            service = DesignService(Path(folder), failed)
            result = service.submit(task())
            self.assertEqual(result["status"], "failed")
            self.assertIsNone(service.current("service-test"))

    def test_passed_message_without_files_is_not_success(self):
        with tempfile.TemporaryDirectory() as folder:
            def incomplete(plan, *args, **kwargs):
                return dict(status="passed", task_id=plan["task_id"], revision=plan["revision"], checks=[], artifacts=[])
            service = DesignService(Path(folder), incomplete)
            self.assertEqual(service.submit(task())["status"], "failed")
            self.assertIsNone(service.current("service-test"))

    def test_protected_change_and_stale_selection_are_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            service = DesignService(Path(folder), receipt_fake)
            self.assertEqual(service.submit(task())["status"], "passed")
            with self.assertRaises(ValueError):
                service.parameter_change("service-test", "length", 81.0, "mm", 1)
            with self.assertRaises(RevisionConflict):
                service.parameter_change("service-test", "hole_diameter", 6.0, "mm", 1,
                                         selection=dict(task_id="service-test", revision=0, parameter_id="hole_diameter"))
            self.assertEqual(service.current("service-test")["revision"], 1)

    def test_new_revision_preserves_source_and_rejects_old_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            service = DesignService(Path(folder), receipt_fake)
            service.submit(task())
            old_state = service.current("service-test")
            original = Path(old_state["result_path"])
            original_hash = sha256(original)
            result = service.parameter_change("service-test", "hole_diameter", 6.0, "mm", 1)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(service.current("service-test")["revision"], 2)
            self.assertEqual(sha256(original), original_hash)
            with self.assertRaises(RevisionConflict):
                service.parameter_change("service-test", "hole_diameter", 7.0, "mm", 1)

    def test_changed_current_model_invalidates_modification(self):
        with tempfile.TemporaryDirectory() as folder:
            service = DesignService(Path(folder), receipt_fake)
            result = service.submit(task())
            Path(result["result"]["artifacts"][0]["path"]).write_bytes(b"modified after review")
            with self.assertRaises(RevisionConflict):
                service.parameter_change("service-test", "hole_diameter", 6.0, "mm", 1)


if __name__ == "__main__":
    unittest.main()
