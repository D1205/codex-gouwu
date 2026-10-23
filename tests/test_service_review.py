"""Unit-only review boundary tests; fake bytes are NEVER real CAD evidence.

This file checks service state transitions and receipt binding in temporary
directories. It does not call SolidWorks, render images or qualify a CAD model.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from mechanical_app.rules import PROJECT_ROOT
from mechanical_app.service import (
    DeliveryRejected, DesignService, RevisionConflict, required_check_ids,
)
from mechanical_app.storage import read_json, sha256, write_json


def fixture_task(*, preview: bool) -> dict:
    task = json.loads((PROJECT_ROOT / "cases/positive/plate-mm.json").read_text(encoding="utf-8"))
    task["task_id"] = "unit-review-boundary"
    task["goal"] = "Synthetic service unit fixture; no actual CAD qualification"
    task["deliverables"] = ["native", "preview"] if preview else ["native"]
    return task


def unit_only_receipt(plan: dict, output: Path, **kwargs) -> dict:
    """Construct ledger-shaped fake files solely to isolate the service layer."""
    artifacts = []

    def fake_file(name: str, kind: str) -> dict:
        path = output / name
        path.write_bytes(("UNIT TEST ONLY; NOT A CAD/IMAGE FILE: " + name).encode("ascii"))
        item = {"kind": kind, "path": str(path), "sha256": sha256(path), "size_bytes": path.stat().st_size}
        artifacts.append(item)
        return item

    native = fake_file("unit-only.sldprt", "native")
    result = {
        "status": "passed", "task_id": plan["task_id"], "revision": plan["revision"],
        "semantic_hash": plan["semantic_hash"],
        "checks": [{"id": key, "status": "passed", "actual": "UNIT ONLY", "expected": "UNIT ONLY"}
                   for key in sorted(required_check_ids(plan))],
        "artifacts": artifacts,
        "not_covered": ["all real CAD and engineering acceptance"],
    }
    if "preview" in plan["deliverables"]:
        fake_file("unit-only.stl", "stl")
        for view in ("isometric", "front", "top", "right"):
            fake_file("unit-only-" + view + ".png", "preview_" + view)
        mapping = {
            "task_id": plan["task_id"], "revision": plan["revision"],
            "semantic_hash": plan["semantic_hash"], "native_sha256": native["sha256"], "units": "mm",
        }
        path = output / "unit-only-mapping.json"
        write_json(path, mapping)
        artifacts.append({"kind": "mapping", "path": str(path), "sha256": sha256(path), "size_bytes": path.stat().st_size})
        result["mapping"] = mapping
        # A worker's claim must not authorize final visual acceptance.
        result["visual_review"] = {"status": "passed", "reviewer": "fake-worker", "notes": "Not inspected"}
    return result


class ReviewBoundaryTests(unittest.TestCase):
    def test_wrong_semantic_hash_cannot_publish(self):
        def wrong_hash(plan, output, **kwargs):
            result = unit_only_receipt(plan, output, **kwargs)
            result["semantic_hash"] = "0" * 64
            return result

        with tempfile.TemporaryDirectory() as folder:
            service = DesignService(Path(folder), wrong_hash)
            receipt = service.submit(fixture_task(preview=False))
            self.assertEqual(receipt["status"], "failed")
            self.assertIn("another semantic plan", receipt["error"])
            self.assertIsNone(service.current("unit-review-boundary"))

    def test_preview_mapping_and_each_of_four_view_files_are_required(self):
        missing_kinds = ["mapping", "preview_isometric", "preview_front", "preview_top", "preview_right"]
        for missing_kind in missing_kinds:
            with self.subTest(missing_kind=missing_kind), tempfile.TemporaryDirectory() as folder:
                def missing_artifact(plan, output, **kwargs):
                    result = unit_only_receipt(plan, output, **kwargs)
                    result["artifacts"] = [item for item in result["artifacts"] if item["kind"] != missing_kind]
                    return result

                service = DesignService(Path(folder), missing_artifact)
                receipt = service.submit(fixture_task(preview=True))
                self.assertEqual(receipt["status"], "failed")
                self.assertIn("all four native CAD views", receipt["error"])
                self.assertIsNone(service.current("unit-review-boundary"))

    def test_worker_visual_pass_still_requires_explicit_service_review(self):
        with tempfile.TemporaryDirectory() as folder:
            service = DesignService(Path(folder), unit_only_receipt)
            receipt = service.submit(fixture_task(preview=True))
            self.assertEqual(receipt["result"]["visual_review"]["status"], "passed")
            self.assertEqual(receipt["status"], "review_required")
            self.assertIsNone(service.current("unit-review-boundary"))
            # This decision validates the unit state machine, not any image.
            approved = service.complete_review(receipt["job_id"], approved=True,
                                               reviewer="unit-test", notes="Unit-only transition fixture, no CAD review")
            self.assertEqual(approved["status"], "passed")
            self.assertEqual(service.current("unit-review-boundary")["revision"], 1)

    def test_pending_task_or_plan_file_changes_prevent_approval(self):
        for name in ("task.json", "plan.json"):
            with self.subTest(file=name), tempfile.TemporaryDirectory() as folder:
                service = DesignService(Path(folder), unit_only_receipt)
                receipt = service.submit(fixture_task(preview=True))
                path = Path(receipt["output_dir"]) / name
                changed = read_json(path)
                if name == "task.json":
                    changed["goal"] = "Changed after execution"
                else:
                    changed["parameters_mm"]["width"] = 55.0
                write_json(path, changed)
                with self.assertRaisesRegex(DeliveryRejected, "fingerprints changed"):
                    service.complete_review(receipt["job_id"], approved=True,
                                            reviewer="unit-test", notes="Unit-only forced decision")
                self.assertIsNone(service.current("unit-review-boundary"))
                self.assertEqual(read_json(Path(folder) / "jobs" / (receipt["job_id"] + ".json"))["status"], "review_required")

    def test_old_baseline_artifact_change_during_review_prevents_publish(self):
        with tempfile.TemporaryDirectory() as folder:
            service = DesignService(Path(folder), unit_only_receipt)
            first = service.submit(fixture_task(preview=False))
            self.assertEqual(first["status"], "passed")
            state = service.current("unit-review-boundary")
            modified = copy.deepcopy(state["task"])
            modified.update(action="modify", revision=2,
                            baseline={"revision": 1, "semantic_hash": state["semantic_hash"]},
                            deliverables=["native", "preview"])
            modified["parameters"]["hole_diameter"]["value"] = 6.0
            pending = service.submit(modified)
            self.assertEqual(pending["status"], "review_required")
            old_native = next(item for item in first["result"]["artifacts"] if item["kind"] == "native")
            Path(old_native["path"]).write_bytes(b"UNIT ONLY: simulated edit to baseline while candidate awaited review")
            with self.assertRaisesRegex(RevisionConflict, "evidence is stale"):
                service.complete_review(pending["job_id"], approved=True,
                                        reviewer="unit-test", notes="Unit-only forced decision")
            current = service.current("unit-review-boundary")
            self.assertEqual(current["revision"], 1)
            self.assertEqual(current["semantic_hash"], state["semantic_hash"])
            self.assertEqual(read_json(Path(folder) / "jobs" / (pending["job_id"] + ".json"))["status"], "review_required")


if __name__ == "__main__":
    unittest.main()
