"""Boundary tests for promises the protocol actually makes; no CAD/LLM calls."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from pydantic import ValidationError
import jsonschema

from mechanical_app.contracts import CADPlan, EngineeringTask
from mechanical_app.rules import (
    LOCKED_SKILL_SHA256, PROJECT_ROOT, TaskRejected, compile_plan, semantic_hash,
    validate_plan, validate_task,
)


def example(name: str = "plate-mm") -> dict:
    return json.loads((PROJECT_ROOT / "cases" / "positive" / (name + ".json")).read_text(encoding="utf-8"))


def codes(task: dict, **kwargs) -> set[str]:
    return {error.code for error in validate_task(task, **kwargs)}


class ContractTests(unittest.TestCase):
    def test_fixed_case_expectations(self):
        manifest = json.loads((PROJECT_ROOT / "cases/manifest.json").read_text(encoding="utf-8"))
        for case in manifest["cases"]:
            with self.subTest(case=case["path"]):
                task = json.loads((PROJECT_ROOT / "cases" / case["path"]).read_text(encoding="utf-8"))
                actual = codes(task, **case.get("validation_context", {}))
                if case["ready"]:
                    self.assertEqual(actual, set())
                    self.assertEqual(validate_plan(compile_plan(task)), [])
                else:
                    self.assertTrue(set(case["expected_codes"]).issubset(actual), actual)
                    if not case.get("validation_context"):
                        with self.assertRaises(TaskRejected):
                            compile_plan(task)

    def test_equal_units_have_identical_semantics(self):
        a = compile_plan(example())
        b = compile_plan(example("plate-cm"))
        self.assertEqual(a.parameters_mm, b.parameters_mm)
        self.assertEqual(a.semantic_hash, b.semantic_hash)

    def test_narrative_provenance_and_task_id_do_not_change_semantics(self):
        a = example()
        b = copy.deepcopy(a)
        b.update(task_id="another-id", goal="Equivalent everyday phrasing")
        b["sources"][0]["reference"] = "A different authority record for the same confirmed dimensions"
        self.assertEqual(compile_plan(a).semantic_hash, compile_plan(b).semantic_hash)

    def test_geometry_deliverables_tolerance_and_constraints_change_semantics(self):
        a = example()
        base = compile_plan(a).semantic_hash
        for mutation in ("geometry", "deliverable", "tolerance", "constraint"):
            b = copy.deepcopy(a)
            if mutation == "geometry":
                b["parameters"]["width"]["value"] = 60
            elif mutation == "deliverable":
                b["deliverables"] = ["native"]
            elif mutation == "tolerance":
                b["tolerance_mm"] = 0.02
            else:
                b["hard_constraints"] = {}
            with self.subTest(mutation=mutation):
                self.assertNotEqual(base, compile_plan(b).semantic_hash)

    def test_unknown_does_not_get_a_default_dimension(self):
        task = example()
        task["parameters"]["height"] = dict(value=None, unit="mm", source_id=None, confirmed=False)
        parsed = EngineeringTask.model_validate(task)
        self.assertIsNone(parsed.parameters["height"].value)
        self.assertIn("unknown_parameter", codes(task))

    def test_proposal_cannot_self_confirm(self):
        for kind in ("rule", "derived"):
            task = example()
            task["sources"][0]["kind"] = kind
            with self.subTest(kind=kind):
                self.assertIn("proposal_unconfirmed", codes(task))

    def test_source_must_exist_and_be_unique(self):
        task = example()
        task["parameters"]["height"]["source_id"] = "missing"
        self.assertIn("source_missing", codes(task))
        task = example()
        task["sources"].append(copy.deepcopy(task["sources"][0]))
        self.assertIn("duplicate_source", codes(task))

    def test_types_and_extra_fields_are_strict(self):
        for value in ("4", True, float("inf"), float("nan")):
            task = example()
            task["parameters"]["height"]["value"] = value
            with self.subTest(value=value):
                self.assertIn("contract_invalid", codes(task))
        task = example()
        task["execute_python"] = "print('must never execute')"
        self.assertIn("contract_invalid", codes(task))

    def test_new_revision_requires_current_baseline(self):
        first = compile_plan(example())
        task = example()
        task.update(action="modify", revision=2, baseline=dict(revision=1, semantic_hash=first.semantic_hash))
        self.assertEqual(validate_task(task, expected_revision=1, expected_baseline_hash=first.semantic_hash), [])
        self.assertIn("stale_revision", codes(task, expected_revision=2))
        self.assertIn("stale_baseline", codes(task, expected_baseline_hash="0" * 64))
        # Same geometry retains a semantic hash even if version or baseline changes.
        self.assertEqual(compile_plan(task).semantic_hash, first.semantic_hash)

    def test_create_cannot_replace_a_ledger_version(self):
        self.assertIn("stale_baseline", codes(example(), expected_revision=1))

    def test_hard_constraint_has_no_unit_ambiguity(self):
        task = example("plate-cm")
        task["hard_constraints"] = {"length": 80}
        self.assertEqual(codes(task), set())
        task["hard_constraints"]["length"] = 8
        self.assertIn("constraint_conflict", codes(task))

    def test_tangent_holes_are_rejected(self):
        task = example()
        task["parameters"]["hole_margin"]["value"] = 2.5
        self.assertIn("hole_breakout", codes(task))
        task["parameters"]["hole_margin"]["value"] = 22.5
        self.assertIn("hole_overlap", codes(task))

    def test_capability_allowlist_cannot_embed_code_or_extra_operation(self):
        plan = compile_plan(example()).model_dump(mode="json")
        plan["operations"][0]["op"] = "execute_python"
        self.assertTrue(validate_plan(plan))
        plan = compile_plan(example()).model_dump(mode="json")
        plan["operations"].append(dict(id="unexpected", op="rebuild", parameters={}))
        self.assertTrue(validate_plan(plan))

    def test_allowed_operation_arguments_cannot_be_tampered(self):
        plan = compile_plan(example()).model_dump(mode="json")
        plan["operations"][0]["parameters"]["width"] = 65
        self.assertTrue(validate_plan(plan))
        plan = compile_plan(example()).model_dump(mode="json")
        plan["parameters_mm"]["width"] = 65
        plan["operations"][0]["parameters"]["width"] = 65
        self.assertIn("plan_tampered", {v.code for v in validate_plan(plan)})

    def test_wrong_skill_version_is_blocked(self):
        task = example()
        task["skill_sha256"] = "0" * 64
        self.assertIn("skill_version", codes(task))

    def test_schema_artifacts_match_models(self):
        for name, model in (("engineering-task", EngineeringTask), ("cad-plan", CADPlan)):
            stored = json.loads((PROJECT_ROOT / "schemas" / (name + "-v2.schema.json")).read_text(encoding="utf-8"))
            self.assertEqual(stored, model.model_json_schema())
            data = example() if name == "engineering-task" else compile_plan(example()).model_dump(mode="json")
            jsonschema.Draft202012Validator(stored).validate(data)
            # The original v1 artifacts remain unchanged and validate legacy packets.
            legacy = json.loads((PROJECT_ROOT / "schemas" / (name + "-v1.schema.json")).read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(legacy).validate(data)


if __name__ == "__main__":
    unittest.main()
