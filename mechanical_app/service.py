"""Versioned application boundary; only verified executions advance a design."""
from __future__ import annotations

from datetime import datetime, timezone
import copy
from pathlib import Path
from typing import Callable
import uuid

from .storage import execution_lease, read_json, safe_id, sha256, verify_artifacts, write_json


class RevisionConflict(ValueError):
    pass


class DeliveryRejected(ValueError):
    pass


def required_check_ids(plan: dict) -> set[str]:
    stages = ["created", "reopened"]
    if "step" in plan["deliverables"]:
        stages.append("step_readback")
    required = {f"{stage}.{name}" for stage in stages
                for name in ("rebuild", "body_count", "feature_health", "volume", "envelope", "origin")}
    required.add("reopened.fully_defined_sketches")
    if plan["schema_version"] == "cad-plan/2":
        required.add("reopened.feature_contracts")
    if plan["schema_version"] == "cad-plan/1" and plan["family"] == "plate":
        required.update(f"{stage}.four_through_holes" for stage in stages)
        required.add("reopened.native_through_all")
    if "preview" in plan["deliverables"]:
        required.add("preview.stl_units_and_origin")
        required.update(f"preview.{view}.nonblank" for view in ("isometric", "front", "top", "right"))
    return required


class DesignService:
    def __init__(self, root: Path, executor: Callable | None = None):
        self.root = Path(root).resolve()
        self.executor = executor

    def _task_root(self, task_id: str) -> Path:
        return self.root / "tasks" / safe_id(task_id)

    def current(self, task_id: str) -> dict | None:
        path = self._task_root(task_id) / "current.json"
        return read_json(path) if path.exists() else None

    @staticmethod
    def _check_delivery(result: dict, plan: dict, output: Path, task: dict) -> list[str]:
        errors = []
        if result.get("status") != "passed":
            errors.append(result.get("error") or "CAD execution did not pass")
        if result.get("task_id") != plan["task_id"] or result.get("revision") != plan["revision"]:
            errors.append("CAD receipt belongs to another task or revision")
        if result.get("semantic_hash") != plan["semantic_hash"]:
            errors.append("CAD receipt belongs to another semantic plan")
        checks = result.get("checks")
        if not isinstance(checks, list) or not checks:
            errors.append("CAD returned no numerical checks")
        elif any(not isinstance(check, dict) or check.get("status") != "passed" for check in checks):
            errors.append("A required CAD check did not pass")
        elif not required_check_ids(plan).issubset({check.get("id") for check in checks}):
            errors.append("Required CAD evidence is incomplete")
        errors.extend(verify_artifacts(result, output))
        artifacts = result.get("artifacts", [])
        suffixes = {Path(item.get("path", "")).suffix.lower() for item in artifacts if isinstance(item, dict)}
        for kind, expected in (("native", {".sldprt"}), ("step", {".step", ".stp"}), ("preview", {".png", ".bmp"})):
            if kind in task.get("deliverables", []) and not (suffixes & expected):
                errors.append(f"Missing requested deliverable: {kind}")
        kinds = {item.get("kind") for item in artifacts if isinstance(item, dict)}
        if "native" not in kinds:
            errors.append("Missing native artifact identity")
        if "step" in task.get("deliverables", []) and "step" not in kinds:
            errors.append("Missing STEP artifact identity")
        if "preview" in task.get("deliverables", []):
            required = {"stl", "mapping"} | {"preview_" + view for view in ("isometric", "front", "top", "right")}
            if not required.issubset(kinds):
                errors.append("Preview requires STL, semantic mapping and all four native CAD views")
            else:
                native = next(item for item in artifacts if item.get("kind") == "native")
                mapping_file = next(item for item in artifacts if item.get("kind") == "mapping")
                try:
                    mapping = read_json(Path(mapping_file["path"]))
                    expected = {"task_id": plan["task_id"], "revision": plan["revision"],
                                "semantic_hash": plan["semantic_hash"], "native_sha256": native["sha256"], "units": "mm"}
                    if any(mapping.get(key) != value for key, value in expected.items()) or mapping != result.get("mapping"):
                        errors.append("Semantic mapping does not match this plan, native model and units")
                except (OSError, ValueError, TypeError):
                    errors.append("Semantic mapping cannot be read")
        return errors

    def _publish(self, task: dict, plan: dict, result: dict, receipt: dict) -> None:
        output = Path(receipt["output_dir"])
        result_path = output / "verified-result.json"
        write_json(result_path, result)
        new_state = {"task_id": task["task_id"], "revision": task["revision"],
                     "semantic_hash": plan["semantic_hash"], "task": task,
                     "result_path": str(result_path), "result_sha256": sha256(result_path),
                     "output_dir": str(output), "job_id": receipt["job_id"]}
        write_json(self._task_root(task["task_id"]) / "current.json", new_state)
        receipt.update(status="passed", result=result, result_path=str(result_path))

    def _verify_current(self, state: dict) -> None:
        result_path = Path(state["result_path"])
        if not result_path.is_file() or sha256(result_path) != state["result_sha256"]:
            raise RevisionConflict("Current evidence changed or is missing; reopen/review before modification")
        errors = verify_artifacts(read_json(result_path), Path(state["output_dir"]))
        if errors:
            raise RevisionConflict("Current model evidence is stale: " + "; ".join(errors))

    def submit(self, data: dict, *, major: int | None = None) -> dict:
        from .contracts import EngineeringTask
        from .rules import compile_plan

        task = EngineeringTask.model_validate(data)
        plan = compile_plan(task).model_dump(mode="json")
        task_data = task.model_dump(mode="json")
        safe_id(task.task_id)
        with execution_lease(self.root):
            if (self._task_root(task.task_id) / "pending-review.json").exists():
                raise RevisionConflict("Review the pending candidate before starting another revision")
            state = self.current(task.task_id)
            if state is None:
                if task.action != "create" or task.revision != 1 or task.baseline is not None:
                    raise RevisionConflict("A new task must start at revision 1 without a baseline")
            else:
                if task.action != "modify" or task.baseline is None:
                    raise RevisionConflict("Task already exists; use a versioned modification")
                if task.baseline.revision != state["revision"] or task.baseline.semantic_hash != state["semantic_hash"]:
                    raise RevisionConflict("Expected revision or baseline plan hash is stale")
                if task.revision != state["revision"] + 1:
                    raise RevisionConflict("Modification must create the next revision")
                self._verify_current(state)
                if task.family != state["task"]["family"] and not (task.schema_version == "engineering-task/2" and state["task"]["schema_version"] == "engineering-task/2"):
                    raise RevisionConflict("Changing the part family requires a new task")
                for parameter_id, value in state["task"].get("hard_constraints", {}).items():
                    if abs(plan.get("parameter_values", plan["parameters_mm"]).get(parameter_id, float("inf")) - value) > 1e-9:
                        raise RevisionConflict(f"Protected interface would change: {parameter_id}")
                    if task.hard_constraints.get(parameter_id) != value:
                        raise RevisionConflict(f"Cannot remove a protected interface implicitly: {parameter_id}")

            job_id = uuid.uuid4().hex
            output = self._task_root(task.task_id) / "revisions" / f"r{task.revision:04d}" / job_id
            output.mkdir(parents=True, exist_ok=False)
            write_json(output / "task.json", task_data)
            write_json(output / "plan.json", plan)
            receipt = {"job_id": job_id, "task_id": task.task_id, "revision": task.revision,
                       "status": "running", "created_at": datetime.now(timezone.utc).isoformat(),
                       "output_dir": str(output), "task_sha256": sha256(output / "task.json"),
                       "plan_sha256": sha256(output / "plan.json")}
            job_path = self.root / "jobs" / f"{job_id}.json"
            write_json(job_path, receipt)
            try:
                executor = self.executor
                if executor is None:
                    from .cad import execute_plan
                    executor = execute_plan
                result = executor(plan, output, major=major)
                errors = self._check_delivery(result, plan, output, task_data)
                if errors:
                    raise DeliveryRejected("; ".join(str(item) for item in errors))
                if "preview" in task.deliverables:
                    receipt.update(status="review_required", result=result)
                    write_json(self._task_root(task.task_id) / "pending-review.json", {"job_id": job_id})
                else:
                    self._publish(task_data, plan, result, receipt)
            except Exception as error:
                receipt.update(status="failed", error=f"{type(error).__name__}: {error}")
            write_json(job_path, receipt)
            return receipt

    def complete_review(self, job_id: str, *, approved: bool, reviewer: str, notes: str) -> dict:
        """Explicit review after looking at the CAD captures; never inferred from file creation."""
        if not isinstance(approved, bool) or not reviewer.strip() or not notes.strip():
            raise ValueError("Review needs an explicit decision, reviewer and observation")
        path = self.root / "jobs" / f"{safe_id(job_id)}.json"
        with execution_lease(self.root):
            receipt = read_json(path)
            if receipt["status"] != "review_required":
                raise RevisionConflict("This job is not awaiting visual review")
            output = Path(receipt["output_dir"])
            if (sha256(output / "task.json") != receipt["task_sha256"]
                    or sha256(output / "plan.json") != receipt["plan_sha256"]):
                raise DeliveryRejected("Pending task or plan fingerprints changed")
            task, plan, result = read_json(output / "task.json"), read_json(output / "plan.json"), receipt["result"]
            from .rules import compile_plan
            if compile_plan(task).model_dump(mode="json") != plan:
                raise DeliveryRejected("Pending plan or task changed after CAD execution")
            current = self.current(task["task_id"])
            previous = current["revision"] if current else 0
            if previous != task["revision"] - 1:
                raise RevisionConflict("Design advanced while this candidate was awaiting review")
            if current:
                baseline = task.get("baseline") or {}
                if (baseline.get("revision") != current["revision"]
                        or baseline.get("semantic_hash") != current["semantic_hash"]):
                    raise RevisionConflict("Baseline changed while this candidate was awaiting review")
                self._verify_current(current)
            pending = read_json(self._task_root(task["task_id"]) / "pending-review.json")
            if pending.get("job_id") != job_id:
                raise RevisionConflict("This is not the active review candidate")
            errors = self._check_delivery(result, plan, output, task)
            if errors:
                raise DeliveryRejected("; ".join(str(error) for error in errors))
            result["visual_review"] = {"status": "passed" if approved else "failed", "reviewer": reviewer, "notes": notes}
            if approved:
                self._publish(task, plan, result, receipt)
            else:
                receipt.update(status="failed", error="Visual review rejected the candidate", result=result)
            write_json(path, receipt)
            (self._task_root(task["task_id"]) / "pending-review.json").unlink()
            return receipt

    def parameter_change(self, task_id: str, parameter_id: str, value: float, unit: str,
                         expected_revision: int, *, major: int | None = None,
                         selection: dict | None = None) -> dict:
        """Explicit scalar changes; a viewport pick must identify this exact revision."""
        state = self.current(task_id)
        if state is None or state["revision"] != expected_revision:
            raise RevisionConflict("The selected design revision is stale or missing")
        if selection is not None:
            if (selection.get("revision") != expected_revision
                    or selection.get("task_id") != task_id
                    or selection.get("parameter_id") != parameter_id
                    or selection.get("semantic_hash") != state["semantic_hash"]):
                raise RevisionConflict("Selection does not identify the current engineering parameter")
        if parameter_id not in state["task"]["parameters"]:
            raise ValueError("Unknown engineering parameter")
        task = copy.deepcopy(state["task"])
        task["action"] = "modify"
        task["revision"] = expected_revision + 1
        task["baseline"] = {"revision": expected_revision, "semantic_hash": state["semantic_hash"]}
        source_id = f"user-edit-{task['revision']}"
        task["sources"].append({"id": source_id, "kind": "user", "reference": "Explicit parameter change"})
        task["parameters"][parameter_id] = {"value": value, "unit": unit, "source_id": source_id, "confirmed": True}
        return self.submit(task, major=major)
