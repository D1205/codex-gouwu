"""Provider changes must preserve local engineering and image confirmation gates."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mechanical_app.agent import _source_supports_value, interpret_brief
from mechanical_app.model_settings import ModelConfig
from mechanical_app.server import Application
from test_agent import BRIEF, candidate


def config(model="test-model"):
    return ModelConfig(kind="openai_compatible", profile_id="custom", name="Test API",
                       base_url="http://127.0.0.1:9999/v1", model=model, vision=True,
                       api_key="dummy-test-credential")


class ProviderIntegrationTests(unittest.TestCase):
    def test_chinese_axis_wording_is_explicit_angular_evidence(self):
        for reference, angle in (("第一孔位于X正方向", 0), ("第一孔位于Y正方向", 90),
                                 ("X轴负方向", 180), ("Y轴负方向", 270)):
            with self.subTest(reference=reference):
                self.assertTrue(_source_supports_value(angle, "deg", reference))
                self.assertFalse(_source_supports_value((angle + 90) % 360, "deg", reference))

    def invoke(self, draft):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        with patch("mechanical_app.model_providers.request_draft", return_value=(draft, {"model": "test-model"})) as transport, \
                patch("mechanical_app.agent._provider") as cli:
            result = interpret_brief(BRIEF, model_config=config(), output_dir=self.root)
            cli.assert_not_called()
            self.assertIn("FIXED_POLICY_BEGIN", transport.call_args.args[1])
            self.assertIn("$defs", transport.call_args.args[2])
        return result

    def test_api_draft_passes_same_local_contract(self):
        result = self.invoke(candidate())
        self.assertEqual(result["status"], "ready", result.get("error"))
        self.assertEqual(result["task"]["parameters"]["height"]["value"], 4)
        evidence = "".join(path.read_text(encoding="utf-8") for path in self.root.rglob("*.json"))
        self.assertNotIn("dummy-test-credential", evidence)

    def test_api_cannot_bypass_engineering_validation(self):
        draft = candidate()
        draft["parameters"][-1]["value"] = 80.0
        result = self.invoke(draft)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["code"], "engineering_validation_failed")

    def test_api_does_not_confirm_recommended_dimensions(self):
        draft = candidate()
        draft["parameters"][-1]["source_kind"] = "rule"
        result = self.invoke(draft)
        self.assertEqual(result["status"], "needs_input")
        self.assertFalse(result["task"]["parameters"]["hole_margin"]["confirmed"])

    def test_api_failure_has_safe_code_and_no_codex_fallback(self):
        from mechanical_app.model_providers import ModelProviderError
        with tempfile.TemporaryDirectory() as directory, \
                patch("mechanical_app.model_providers.request_draft", side_effect=ModelProviderError("model_http_error", "API unavailable")), \
                patch("mechanical_app.agent._provider") as cli:
            result = interpret_brief(BRIEF, model_config=config(), output_dir=Path(directory))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["code"], "model_http_error")
        cli.assert_not_called()

    def test_missing_credential_does_not_claim_model_invocation(self):
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as directory, patch("mechanical_app.agent._provider") as cli:
            result = interpret_brief(BRIEF, model_config=replace(config(), api_key=""), output_dir=Path(directory))
        self.assertEqual(result["error"]["code"], "model_missing_api_key")
        self.assertFalse(result["runtime"]["model_invoked"])
        cli.assert_not_called()

    def test_inflight_interpret_keeps_submission_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = SimpleNamespace(snapshot=lambda: config("before-save"))
            application = Application(Path(directory), settings=settings)
            self.addCleanup(application.pool.shutdown, wait=True)
            with patch.object(application, "start", side_effect=lambda function: function()) as start, \
                    patch("mechanical_app.agent.interpret_brief", return_value={"status": "needs_input"}) as interpret:
                # Replacing active config between queueing and execution cannot affect the snapshot.
                def execute_after_change(function):
                    settings.snapshot = lambda: config("after-save")
                    return function()
                start.side_effect = execute_after_change
                application.dispatch("/api/interpret", {"brief": BRIEF})
            self.assertEqual(interpret.call_args.kwargs["model_config"].model, "before-save")


if __name__ == "__main__":
    unittest.main()
