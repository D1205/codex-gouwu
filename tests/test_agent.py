"""Adapter unit tests mock the transport; live evidence is only verify_agent.py."""
import json
from contextlib import nullcontext
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mechanical_app.agent import RequirementDraft, RequirementDraftV2, _command, _prompt, _source_supports_value, _subprocess_environment, interpret_brief


BRIEF = "底板长80毫米宽50毫米厚4毫米，四个直径5毫米通孔，孔中心距边10毫米。"
FLANGE_BRIEF = "圆形平法兰外径100毫米、厚10毫米、中心贯穿孔40毫米，4个直径9毫米螺栓贯穿孔均布在75毫米分度圆，第一孔朝+X，不带颈和其他结构，几何评审"


def candidate():
    values = {"length": 80.0, "width": 50.0, "height": 4.0, "hole_diameter": 5.0, "hole_margin": 10.0}
    return {
        "schema_version": "requirement-draft/1", "family": "plate", "goal": "四孔底板几何评审",
        "parameters": [
            {"name": name, "value": value, "unit": "mm", "source_kind": "user", "source_reference": BRIEF, "confirmed": True}
            for name, value in values.items()
        ], "hard_constraints": [], "questions": [], "conflicts": [], "unsupported_requirements": [],
    }


def flange_candidate():
    values = [
        ("outer_diameter", 100.0, "mm", "外径100毫米"),
        ("thickness", 10.0, "mm", "厚10毫米"),
        ("center_hole_diameter", 40.0, "mm", "中心贯穿孔40毫米"),
        ("bolt_count", 4.0, "count", "4个直径9毫米螺栓贯穿孔"),
        ("bolt_hole_diameter", 9.0, "mm", "直径9毫米螺栓贯穿孔"),
        ("bolt_circle_diameter", 75.0, "mm", "75毫米分度圆"),
        ("first_hole_angle", 0.0, "deg", "第一孔朝+X"),
    ]
    def circle(identifier, operation, diameter, pattern=None):
        return {"id": identifier, "operation": operation,
                "profile": {"kind": "circle", "center": [0, 0], "diameter": diameter, "size": [], "points": []},
                "start": 0, "depth": "thickness", "pattern": pattern}
    return {
        "schema_version": "requirement-draft/2", "family": "flange", "goal": "圆形平法兰几何评审",
        "parameters": [{"name": name, "value": value, "unit": unit, "source_kind": "user",
                        "source_reference": reference, "confirmed": True} for name, value, unit, reference in values],
        "features": [circle("disk", "add", "outer_diameter"), circle("center_bore", "cut", "center_hole_diameter"),
                     circle("bolt_holes", "cut", "bolt_hole_diameter", {
                         "kind": "circular", "count": "bolt_count", "radius": "bolt_circle_diameter/2",
                         "angle_deg": "first_hole_angle", "step": [0, 0]})],
        "hard_constraints": [], "questions": [], "conflicts": [], "unsupported_requirements": [],
    }


class AgentTests(unittest.TestCase):
    def invoke(self, value=None, *, stdout='{"type":"turn.completed"}\n', returncode=0, exception=None, brief=BRIEF, current_task=None):
        def run(argv, **kwargs):
            self.assertFalse(kwargs["shell"])
            self.assertIn(brief, kwargs["input"])
            if exception is not None:
                raise exception
            Path(argv[argv.index("-o") + 1]).write_text(json.dumps(value), encoding="utf-8")
            return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="test transport")
        with tempfile.TemporaryDirectory() as directory, patch("mechanical_app.agent._provider", return_value=SimpleNamespace(command=("codex-test.exe",))), patch("mechanical_app.agent.subprocess.run", side_effect=run):
            result = interpret_brief(brief, current_task=current_task, output_dir=Path(directory))
            self.assertTrue((Path(result["evidence_dir"]) / "result.json").is_file())
            return result

    def test_schema_forbids_extra_fields(self):
        value = candidate()
        value["execute_python"] = "anything"
        with self.assertRaises(ValueError):
            RequirementDraft.model_validate(value)

    def test_ready_requires_local_rule_success(self):
        result = self.invoke(candidate())
        self.assertEqual(result["status"], "ready", result)
        self.assertEqual(result["task"]["parameters"]["height"]["value"], 4)
        self.assertTrue(result["runtime"]["model_invoked"])

    def test_missing_dimension_is_not_ready(self):
        value = candidate()
        value["parameters"][-1].update(value=None, unit=None, confirmed=False, source_reference=None)
        result = self.invoke(value)
        self.assertEqual(result["status"], "needs_input", result)
        self.assertIsNone(result["task"]["parameters"]["hole_margin"]["value"])
        self.assertTrue(result["questions"])

    def test_guessed_value_is_not_user_confirmation(self):
        value = candidate()
        value["parameters"][-1].update(source_kind="rule", confirmed=True)
        result = self.invoke(value)
        self.assertEqual(result["status"], "needs_input", result)
        self.assertFalse(result["task"]["parameters"]["hole_margin"]["confirmed"])

    def test_hallucinated_source_rejected(self):
        value = candidate()
        value["parameters"][0]["source_reference"] = "用户从未说过的长度"
        result = self.invoke(value)
        self.assertEqual(result["status"], "failed")

    def test_duplicate_parameter_rejected(self):
        value = candidate()
        value["parameters"].append(value["parameters"][0])
        self.assertEqual(self.invoke(value)["status"], "failed")

    def test_fabricated_authoritative_evidence_is_not_ready(self):
        value = candidate()
        value["parameters"][0].update(source_kind="spec", source_reference="unread-spec.pdf")
        self.assertEqual(self.invoke(value)["status"], "needs_input")

    def test_nonzero_exit_never_passes_even_with_valid_json(self):
        result = self.invoke(candidate(), returncode=1)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["code"], "model_call_failed")
        self.assertIsNone(result["task"])

    def test_timeout_has_no_fallback(self):
        result = self.invoke(exception=subprocess.TimeoutExpired("codex", 120, output=b"partial"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["code"], "model_timeout")

    def test_missing_completed_event_rejected(self):
        self.assertEqual(self.invoke(candidate(), stdout="")["status"], "failed")

    def test_bad_json_rejected(self):
        self.assertEqual(self.invoke({"unrecognised": True})["status"], "failed")

    def test_tool_use_rejected(self):
        events = '{"type":"item.completed","item":{"type":"command_execution"}}\n{"type":"turn.completed"}\n'
        self.assertEqual(self.invoke(candidate(), stdout=events)["status"], "failed")

    def test_unsupported_geometry_not_silently_dropped(self):
        value = candidate()
        value["unsupported_requirements"] = ["要求的圆角不在当前能力中"]
        self.assertEqual(self.invoke(value)["status"], "needs_input")

    def test_subprocess_has_fixed_read_only_no_tools(self):
        argv = _command(["codex.exe"], Path("work"), Path("schema.json"), Path("output.json"))
        self.assertEqual(argv[-1], "-")
        self.assertIn("read-only", argv)
        self.assertIn("--ignore-user-config", argv)
        self.assertIn("shell_tool", argv)
        self.assertNotIn(BRIEF, argv)

    def test_existing_proxy_environment_takes_precedence(self):
        with patch.dict("os.environ", {"HTTPS_PROXY": "http://explicit.example:1234"}, clear=True):
            environment, source = _subprocess_environment()
        self.assertEqual(source, "environment")
        self.assertEqual(environment["HTTPS_PROXY"], "http://explicit.example:1234")
        self.assertNotIn("HTTP_PROXY", environment)

    def test_missing_proxy_does_not_guess_endpoint(self):
        registry = SimpleNamespace(
            HKEY_CURRENT_USER=1,
            OpenKey=lambda *args: nullcontext("key"),
            QueryValueEx=lambda key, name: (0 if name == "ProxyEnable" else "", 0),
        )
        with patch.dict("os.environ", {}, clear=True), patch("mechanical_app.agent.os.name", "nt"), patch.dict("sys.modules", {"winreg": registry}):
            environment, source = _subprocess_environment()
        self.assertEqual(source, "none")
        self.assertNotIn("HTTPS_PROXY", environment)

    def test_system_proxy_is_child_environment_only(self):
        registry = SimpleNamespace(
            HKEY_CURRENT_USER=1,
            OpenKey=lambda *args: nullcontext("key"),
            QueryValueEx=lambda key, name: (1 if name == "ProxyEnable" else "127.0.0.1:7890", 0),
        )
        with patch.dict("os.environ", {}, clear=True), patch("mechanical_app.agent.os.name", "nt"), patch.dict("sys.modules", {"winreg": registry}):
            environment, source = _subprocess_environment()
            import os
            self.assertNotIn("HTTPS_PROXY", os.environ)
        self.assertEqual(source, "windows_system")
        self.assertEqual(environment["HTTPS_PROXY"], "http://127.0.0.1:7890")

    def test_proxy_address_not_written_to_result(self):
        with patch("mechanical_app.agent._subprocess_environment", return_value=({"HTTPS_PROXY": "http://private-proxy.example:1234"}, "environment")):
            result = self.invoke(candidate())
        self.assertNotIn("private-proxy", json.dumps(result))

    def test_open_family_flange_reaches_versioned_feature_task(self):
        result = self.invoke(flange_candidate(), brief=FLANGE_BRIEF)
        self.assertEqual(result["status"], "ready", result)
        self.assertEqual(result["task"]["schema_version"], "engineering-task/2")
        self.assertEqual(result["task"]["family"], "flange")
        self.assertEqual(result["task"]["features"][2]["pattern"]["count"], "bolt_count")
        self.assertEqual(result["task"]["parameters"]["first_hole_angle"]["unit"], "deg")

    def test_bare_flange_stays_flange_with_unknown_dimensions(self):
        value = flange_candidate()
        value["features"] = []
        value["questions"] = ["请提供外径和厚度，并说明是否有中心孔及螺栓孔。"]
        for parameter in value["parameters"]:
            parameter.update(value=None, unit=None, source_reference=None, confirmed=False)
        result = self.invoke(value, brief="我想要设计一个圆形的法兰盘")
        self.assertEqual(result["status"], "needs_input", result)
        self.assertEqual(result["task"]["family"], "flange")
        self.assertEqual(result["unsupported_requirements"], [])
        self.assertTrue(all(item["value"] is None for item in result["task"]["parameters"].values()))

    def test_v2_quoted_but_different_numeric_size_rejected(self):
        value = flange_candidate()
        value["parameters"][0]["value"] = 120
        result = self.invoke(value, brief=FLANGE_BRIEF)
        self.assertEqual(result["status"], "failed", result)
        self.assertIn("asserted value", result["error"]["message"])

    def test_v2_hidden_unconfirmed_size_in_feature_rejected(self):
        value = flange_candidate()
        value["features"][0]["profile"]["diameter"] = 100
        result = self.invoke(value, brief=FLANGE_BRIEF)
        self.assertEqual(result["status"], "failed", result)

    def test_v2_feature_cannot_contain_code(self):
        value = flange_candidate()
        value["features"][0]["profile"]["diameter"] = "__import__('os').getcwd()"
        result = self.invoke(value, brief=FLANGE_BRIEF)
        self.assertEqual(result["status"], "failed", result)

    def test_v2_name_does_not_silently_approve_unimplemented_thread(self):
        value = flange_candidate()
        value["family"] = "threaded_flange"
        value["unsupported_requirements"] = ["尚缺真实螺旋螺纹特征执行器，需确认牙型和规格。"]
        result = self.invoke(value, brief=FLANGE_BRIEF)
        self.assertEqual(result["status"], "needs_input", result)
        self.assertEqual(result["task"]["family"], "threaded_flange")

    def test_v2_schema_rejects_arbitrary_execution_fields(self):
        value = flange_candidate()
        value["features"][0]["python"] = "print('not allowed')"
        with self.assertRaises(ValueError):
            RequirementDraftV2.model_validate(value)

    def test_new_prompt_uses_open_vocabulary_and_legacy_edit_stays_v1(self):
        prompt = _prompt("法兰", None, None, "policy")
        self.assertIn("requirement-draft/2", prompt)
        self.assertNotIn("SUPPORTED FAMILIES", prompt)
        legacy = _prompt("改厚度", {"schema_version": "engineering-task/1"}, None, "policy")
        self.assertIn("requirement-draft/1", legacy)

    def test_v2_numeric_evidence_accepts_chinese_numbers_and_axis_direction(self):
        self.assertTrue(_source_supports_value(100, "mm", "外径一百毫米"))
        self.assertTrue(_source_supports_value(2.5, "mm", "厚度二点五毫米"))
        self.assertTrue(_source_supports_value(4, "count", "四个螺栓孔"))
        self.assertTrue(_source_supports_value(0, "deg", "第一孔朝正X方向"))
        self.assertFalse(_source_supports_value(120, "mm", "外径一百毫米"))


if __name__ == "__main__":
    unittest.main()
