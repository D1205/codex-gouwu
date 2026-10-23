"""Geometry and compatibility boundaries of open feature tasks; no COM/LLM."""
import copy
import math
import unittest

from mechanical_app.generic_geometry import expected_geometry
from mechanical_app.rules import compile_plan, validate_plan, validate_task, LOCKED_SKILL_SHA256
from mechanical_app.service import required_check_ids


def circle(identifier, diameter, depth, *, operation="add", start=0, pattern=None):
    return {"id": identifier, "operation": operation,
            "profile": {"kind": "circle", "center": [0, 0], "diameter": diameter, "size": [], "points": []},
            "start": start, "depth": depth, "pattern": pattern}


def flange():
    parameters = {"outer_diameter": (100, "mm"), "thickness": (10, "mm"),
                  "bore_diameter": (40, "mm"), "hole_diameter": (9, "mm"),
                  "bolt_circle_diameter": (75, "mm"), "hole_count": (4, "count")}
    return {"schema_version": "engineering-task/2", "task_id": "open-flange", "revision": 1,
            "action": "create", "family": "flange", "goal": "平法兰，仅几何评审", "scope": "geometry_review",
            "sources": [{"id": "user-spec", "kind": "user", "reference": "Confirmed flange test dimensions"}],
            "parameters": {name: {"value": value, "unit": unit, "source_id": "user-spec", "confirmed": True}
                           for name, (value, unit) in parameters.items()},
            "features": [circle("disc", "outer_diameter", "thickness"),
                         circle("bore", "bore_diameter", "thickness", operation="cut"),
                         circle("bolts", "hole_diameter", "thickness", operation="cut", pattern={
                             "kind": "circular", "count": "hole_count", "radius": "bolt_circle_diameter/2",
                             "angle_deg": 0, "step": [0, 0]})],
            "hard_constraints": {}, "baseline": None, "deliverables": ["native", "step", "preview"],
            "tolerance_mm": 0.01, "rule_set_version": "engineering-rules/2", "skill_sha256": LOCKED_SKILL_SHA256}


def codes(task):
    return {error.code for error in validate_task(task)}


class FeatureTests(unittest.TestCase):
    def test_part_name_is_not_a_capability_allowlist(self):
        for family in ("flange", "wheel_hub", "my_new_part", "plate"):
            with self.subTest(family=family):
                task = flange(); task["family"] = family
                plan = compile_plan(task)
                self.assertEqual(validate_plan(plan), [])
                self.assertNotIn("created.four_through_holes", required_check_ids(plan.model_dump()))
                self.assertIn("reopened.feature_contracts", required_check_ids(plan.model_dump()))

    def test_independent_flange_csg_matches_analytic_volume_and_holes(self):
        plan = compile_plan(flange())
        geometry = expected_geometry([f.model_dump() for f in plan.features])
        expected = math.pi / 4 * (100 ** 2 - 40 ** 2 - 4 * 9 ** 2) * 10
        self.assertAlmostEqual(geometry["volume_mm3"] / expected, 1, places=6)
        self.assertEqual(geometry["minimum_mm"], [-50, -50, 0])
        self.assertEqual(geometry["maximum_mm"], [50, 50, 10])
        self.assertEqual(len(geometry["steps"]), 6)
        self.assertEqual(plan.parameter_units["hole_count"], "count")
        self.assertNotIn("hole_count", plan.parameters_mm)
        self.assertEqual(plan.parameter_bindings["hole_count"], ["bolts.pattern.count"])

    def test_equivalent_length_units_preserve_semantics(self):
        first = flange(); second = copy.deepcopy(first)
        for p in second["parameters"].values():
            if p["unit"] == "mm":
                p.update(value=p["value"] / 10, unit="cm")
        self.assertEqual(compile_plan(first).semantic_hash, compile_plan(second).semantic_hash)

    def test_null_count_and_derived_confirmation_do_not_execute(self):
        task = flange(); task["parameters"]["hole_count"].update(value=None, confirmed=False)
        self.assertIn("unknown_parameter", codes(task))
        task = flange(); task["sources"][0]["kind"] = "derived"
        self.assertIn("proposal_unconfirmed", codes(task))

    def test_invalid_or_untraceable_feature_values_are_rejected(self):
        for value in (100, "100", "outer_diameter + hole_count", "outer_diameter+hole_count*0", "outer_diameter+(hole_count-hole_count)", "__import__('os').getcwd()", "outer_diameter/0", "unknown_size"):
            with self.subTest(value=value):
                task = flange(); task["features"][0]["profile"]["diameter"] = value
                self.assertIn("feature_invalid", codes(task))

    def test_unused_confirmed_requirement_cannot_be_silently_dropped(self):
        task = flange(); task["parameters"]["slot_width"] = copy.deepcopy(task["parameters"]["hole_diameter"])
        self.assertIn("feature_invalid", codes(task))

    def test_cut_with_no_effect_and_complete_removal_are_rejected(self):
        for change in ("outside", "remove_all"):
            task = flange()
            if change == "outside":
                task["features"][1]["profile"]["center"] = ["outer_diameter*2", 0]
            else:
                task["features"][1]["profile"]["diameter"] = "outer_diameter"
                task["parameters"].pop("bore_diameter")
            self.assertIn("feature_invalid", codes(task))

    def test_disconnected_additions_are_not_a_single_part(self):
        task = flange()
        extra = circle("floating", "bore_diameter", "thickness")
        extra["profile"]["center"] = ["outer_diameter*2", 0]
        task["features"].append(extra)
        self.assertIn("feature_invalid", codes(task))

    def test_mutated_numeric_features_cannot_detach_from_recipe(self):
        plan = compile_plan(flange()).model_dump(mode="json")
        plan["features"][0]["profile"]["diameter"] = 110
        self.assertTrue(validate_plan(plan))

    def test_malformed_expression_plan_returns_a_blocker(self):
        plan = compile_plan(flange()).model_dump(mode="json")
        plan["feature_recipe"][0]["profile"]["diameter"] = "outer_diameter+"
        self.assertTrue(validate_plan(plan))
        plan = compile_plan(flange()).model_dump(mode="json")
        plan["parameter_bindings"]["hole_count"] = []
        self.assertTrue(validate_plan(plan))

    def test_legacy_packets_do_not_gain_open_features(self):
        task = flange(); task.update(schema_version="engineering-task/1", rule_set_version="engineering-rules/1", family="plate")
        self.assertIn("contract_invalid", codes(task))


if __name__ == "__main__":
    unittest.main()
