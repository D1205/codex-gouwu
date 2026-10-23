"""Focused protocol and secret-safety checks against mock HTTP responses."""
from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from mechanical_app.model_providers import ModelProviderError, _NoRedirect, request_draft, test_connection
from mechanical_app.model_settings import ModelConfig


KEY = "test-secret-api-key-not-a-real-credential"
CONFIG = ModelConfig("openai_compatible", "deepseek", "DeepSeek", "https://api.deepseek.com", "deepseek-flash", True, KEY, "deepseek")
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


class Response(BytesIO):
    status = 200

    def read1(self, size):
        return self.read(size)


def response(value=None, *, content=None, finish="stop", **message):
    return Response(json.dumps({"choices": [{"finish_reason": finish, "message": {"content": json.dumps(value or {"ok": True}) if content is None else content, **message}}]}).encode())


class ProviderTests(unittest.TestCase):
    def test_deepseek_request_and_safe_runtime(self):
        with patch("mechanical_app.model_providers._open", return_value=response()) as opening:
            draft, runtime = request_draft(CONFIG, "engineering brief", SCHEMA, timeout=10)
        request = opening.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + KEY)
        payload = json.loads(request.data)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertIsInstance(payload["messages"][-1]["content"], str)
        self.assertIn(json.dumps(SCHEMA), payload["messages"][-1]["content"])
        self.assertEqual(draft, {"ok": True})
        self.assertNotIn(KEY, json.dumps(runtime))
        self.assertNotIn("engineering brief", json.dumps(runtime))

    def test_custom_endpoint_keeps_model_and_has_no_deepseek_extension(self):
        config = replace(CONFIG, preset="custom", base_url="http://127.0.0.1:8080/v1", model="my-custom-vision-model")
        with patch("mechanical_app.model_providers._open", return_value=response()) as opening:
            request_draft(config, "brief", SCHEMA)
        request = opening.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "http://127.0.0.1:8080/v1/chat/completions")
        self.assertEqual(payload["model"], "my-custom-vision-model")
        self.assertNotIn("thinking", payload)

    def test_png_attached_inline_and_vision_disabled_rejected_before_http(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "reference.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nnormalized-pixel-fixture")
            with patch("mechanical_app.model_providers._open", return_value=response()) as opening:
                request_draft(CONFIG, "brief", SCHEMA, [image])
                payload = json.loads(opening.call_args.args[0].data)
                attachment = payload["messages"][-1]["content"][1]
                self.assertEqual(attachment["type"], "image_url")
                self.assertTrue(attachment["image_url"]["url"].startswith("data:image/png;base64,"))
            with patch("mechanical_app.model_providers._open") as opening:
                with self.assertRaises(ModelProviderError) as caught:
                    request_draft(replace(CONFIG, vision=False), "brief", SCHEMA, [image])
                self.assertEqual(caught.exception.code, "model_vision_unsupported")
                opening.assert_not_called()

    def test_missing_key_does_not_call_endpoint(self):
        with patch("mechanical_app.model_providers._open") as opening:
            with self.assertRaises(ModelProviderError) as caught:
                request_draft(replace(CONFIG, api_key=""), "brief", SCHEMA)
            self.assertEqual(caught.exception.code, "model_missing_api_key")
            opening.assert_not_called()

    def test_http_network_and_timeout_errors_never_echo_private_details(self):
        for error, code in (
            (HTTPError("https://example.org/" + KEY, 401, KEY, {}, BytesIO(KEY.encode())), "model_http_error"),
            (HTTPError("https://example.org/" + KEY, 302, KEY, {"Location": "https://evil.example/" + KEY}, BytesIO(KEY.encode())), "model_http_error"),
            (URLError(KEY), "model_network_error"),
            (TimeoutError(KEY), "model_timeout"),
            (RuntimeError("data:image/png;base64," + KEY), "model_network_error"),
        ):
            with self.subTest(error=type(error).__name__), patch("mechanical_app.model_providers._open", side_effect=error):
                with self.assertRaises(ModelProviderError) as caught:
                    request_draft(CONFIG, "private engineering prompt", SCHEMA)
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn(KEY, str(caught.exception))
                self.assertNotIn("data:image", str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)

    def test_redirect_handler_refuses_authorized_request(self):
        request = Request("https://example.org", headers={"Authorization": "Bearer " + KEY})
        self.assertIsNone(_NoRedirect().redirect_request(request, None, 302, "Found", {}, "https://other.example"))

    def test_truncation_tool_calls_refusal_bad_json_and_secret_reflection_rejected(self):
        factories = (
            lambda: response(finish="length"), lambda: response(tool_calls=[{"id": "tool"}]),
            lambda: response(refusal="cannot answer"), lambda: response(content="```json\n{}\n```"),
            lambda: response(content='{"ok":NaN}'), lambda: response(content="[]"),
            lambda: response(content=json.dumps({"ok": KEY})),
            lambda: response(content=json.dumps({"ok": KEY}).replace("-", "\\u002d")),
        )
        for factory in factories:
            with self.subTest(factory=factory), patch("mechanical_app.model_providers._open", return_value=factory()):
                with self.assertRaises(ModelProviderError) as caught:
                    request_draft(CONFIG, "brief", SCHEMA)
                self.assertEqual(caught.exception.code, "model_invalid_response")
                self.assertNotIn(KEY, str(caught.exception))

    def test_response_size_bound_and_connection_test_shape(self):
        with patch("mechanical_app.model_providers.MAX_RESPONSE_BYTES", 128), patch("mechanical_app.model_providers._open", return_value=Response(b"x" * 129)):
            with self.assertRaises(ModelProviderError) as caught:
                request_draft(CONFIG, "brief", SCHEMA)
            self.assertEqual(caught.exception.code, "model_response_too_large")
        with patch("mechanical_app.model_providers._open", return_value=response()):
            result = test_connection(CONFIG)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "ready")
        self.assertNotIn(KEY, json.dumps(result))


if __name__ == "__main__":
    unittest.main()
