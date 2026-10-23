"""Small, bounded OpenAI-compatible HTTP transport with safe failure messages."""
from __future__ import annotations

import base64
import json
import math
from pathlib import Path
import socket
import time
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .model_settings import ModelConfig, SettingsError, normalize_base_url


MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_REQUEST_BYTES = 96 * 1024 * 1024
DEEPSEEK_MAX_REQUEST_BYTES = 48 * 1024 * 1024


class ModelProviderError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward Authorization to a redirect target, including the same host.
        return None


def _open(request: Request, timeout: float):
    return build_opener(_NoRedirect()).open(request, timeout=timeout)


def _timeout(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 600:
        raise ModelProviderError("model_config_invalid", "Model timeout must be greater than zero and no more than 600 seconds")
    return float(value)


def _validate_config(config: ModelConfig) -> str:
    try:
        if config.kind != "openai_compatible":
            raise SettingsError("HTTP transport requires an OpenAI-compatible model profile")
        base = normalize_base_url(config.base_url)
        if not isinstance(config.model, str) or not config.model.strip() or len(config.model) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in config.model):
            raise SettingsError("A model name is required")
        if not isinstance(config.api_key, str) or len(config.api_key) > 8192 or any(ord(c) < 32 or ord(c) == 127 for c in config.api_key):
            raise SettingsError("Invalid API key")
        if not config.api_key.strip():
            raise ModelProviderError("model_missing_api_key", "Save an API key for the selected model before connecting")
        # HTTP header values must be representable without adding new header lines.
        config.api_key.encode("ascii")
    except (SettingsError, UnicodeError):
        raise ModelProviderError("model_config_invalid", "Model settings are invalid; check the endpoint, model and API key") from None
    return base


def _image_content(images: Iterable[Path], vision: bool) -> list[dict[str, Any]]:
    paths = list(images)
    if len(paths) > 6:
        raise ModelProviderError("model_config_invalid", "At most six reference images can be sent")
    if paths and not vision:
        raise ModelProviderError("model_vision_unsupported", "The selected model has vision disabled; enable vision or select a vision model")
    result, total = [], 0
    for path in paths:
        try:
            with Path(path).open("rb") as stream:
                data = stream.read(MAX_IMAGE_BYTES - total + 1)
        except (OSError, TypeError, ValueError):
            raise ModelProviderError("model_config_invalid", "A reference image could not be read") from None
        total += len(data)
        if total > MAX_IMAGE_BYTES:
            raise ModelProviderError("model_config_invalid", "Reference images exceed the 64 MiB request limit")
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ModelProviderError("model_config_invalid", "Reference images must be normalized PNG files")
        result.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(data).decode("ascii")}})
    return result


def _read_response(response: Any, deadline: float) -> bytes:
    blocks, size = [], 0
    read = getattr(response, "read1", response.read)
    while True:
        if time.monotonic() >= deadline:
            raise ModelProviderError("model_timeout", "The model request timed out")
        block = read(min(64 * 1024, MAX_RESPONSE_BYTES - size + 1))
        if not block:
            return b"".join(blocks)
        size += len(block)
        if size > MAX_RESPONSE_BYTES:
            raise ModelProviderError("model_response_too_large", "The model response exceeded the size limit")
        blocks.append(block)


def _http_json(config: ModelConfig, payload: dict[str, Any], timeout: float) -> tuple[dict[str, Any], float]:
    base = _validate_config(config)
    try:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise ModelProviderError("model_config_invalid", "The model request could not be encoded") from None
    request_limit = DEEPSEEK_MAX_REQUEST_BYTES if config.preset == "deepseek" else MAX_REQUEST_BYTES
    if len(body) > request_limit:
        raise ModelProviderError("model_config_invalid", "The model request exceeded the size limit")
    request = Request(base + "/chat/completions", data=body, method="POST", headers={
        "Authorization": "Bearer " + config.api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    started = time.monotonic()
    try:
        with _open(request, timeout) as response:
            status = response.status
            if status != 200:
                raise ModelProviderError("model_http_error", f"The model endpoint returned HTTP {int(status)}")
            raw = _read_response(response, started + timeout)
    except HTTPError as error:
        # Do not read or print the provider body, headers, URL or request object.
        status = error.code
        try:
            error.close()
        except Exception:
            pass
        if status in {301, 302, 303, 307, 308}:
            raise ModelProviderError("model_http_error", "The model endpoint redirected the request; save its final base URL") from None
        messages = {401: "API key authentication failed (HTTP 401)", 403: "The model endpoint denied access (HTTP 403)",
                    404: "The endpoint or model was not found (HTTP 404)", 429: "The model endpoint rate or credit limit was reached (HTTP 429)"}
        raise ModelProviderError("model_http_error", messages.get(status, f"The model endpoint returned HTTP {int(status)}")) from None
    except (TimeoutError, socket.timeout):
        raise ModelProviderError("model_timeout", "The model request timed out") from None
    except URLError as error:
        if isinstance(error.reason, (TimeoutError, socket.timeout)):
            raise ModelProviderError("model_timeout", "The model request timed out") from None
        raise ModelProviderError("model_network_error", "Could not connect to the model endpoint; check its address and network connection") from None
    except ModelProviderError:
        raise
    except Exception:
        # Some TLS/proxy/HTTP failures include request data in their exception text.
        raise ModelProviderError("model_network_error", "The model connection failed") from None
    try:
        result = json.loads(raw.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(result, dict):
            raise ValueError
    except (ValueError, UnicodeError, RecursionError):
        raise ModelProviderError("model_invalid_response", "The model endpoint did not return a valid JSON response") from None
    return result, round(time.monotonic() - started, 3)


def _completion_object(response: dict[str, Any], api_key: str) -> dict[str, Any]:
    try:
        choices = response["choices"]
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError
        choice = choices[0]
        message = choice["message"]
        if choice["finish_reason"] != "stop" or message.get("tool_calls") or message.get("function_call") or message.get("refusal"):
            raise ValueError
        content = message["content"]
        if not isinstance(content, str) or not content.strip() or len(content.encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise ValueError
        # A misbehaving endpoint must not reflect an Authorization value into evidence.
        if api_key and api_key in content:
            raise ValueError
        result = json.loads(content, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(result, dict) or (api_key and api_key in json.dumps(result, ensure_ascii=False)):
            raise ValueError
        return result
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError, RecursionError):
        raise ModelProviderError("model_invalid_response", "The model did not finish with one valid JSON object; try again or check model compatibility") from None


def request_draft(config: ModelConfig, prompt: str, schema: dict[str, Any],
                  images: Iterable[Path] = (), timeout: float = 120) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return untrusted draft JSON; the caller must apply local schema and rules."""
    timeout = _timeout(timeout)
    _validate_config(config)
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode("utf-8")) > 2 * 1024 * 1024 or not isinstance(schema, dict):
        raise ModelProviderError("model_config_invalid", "A model prompt and JSON schema are required")
    try:
        schema_json = json.dumps(schema, ensure_ascii=False, allow_nan=False)
        if len(schema_json.encode("utf-8")) > 1024 * 1024:
            raise ValueError
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ModelProviderError("model_config_invalid", "The model JSON schema is invalid") from None
    text = prompt + "\n\nReturn only a JSON object matching this JSON Schema:\n" + schema_json
    attachments = _image_content(images, config.vision)
    content = [{"type": "text", "text": text}, *attachments] if attachments else text
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": "Extract the requested mechanical engineering draft. Return exactly one JSON object. Follow the supplied JSON Schema and local engineering rules. Do not invoke tools."},
            {"role": "user", "content": content},
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    if config.preset == "deepseek":
        payload["thinking"] = {"type": "disabled"}
    response, elapsed = _http_json(config, payload, timeout)
    draft = _completion_object(response, config.api_key)
    runtime = {"provider": config.kind, "profile_id": config.profile_id, "provider_name": config.name,
               "model": config.model, "base_url": normalize_base_url(config.base_url), "model_invoked": True,
               "transport": "chat_completions", "elapsed_seconds": elapsed}
    return draft, runtime


def test_connection(config: ModelConfig, timeout: float = 30) -> dict[str, Any]:
    schema = {"type": "object", "properties": {"ok": {"type": "boolean", "const": True}}, "required": ["ok"], "additionalProperties": False}
    draft, runtime = request_draft(config, 'Connection test: reply with {"ok":true}.', schema, timeout=timeout)
    if draft != {"ok": True} or type(draft.get("ok")) is not bool:
        raise ModelProviderError("model_invalid_response", "The model connected but did not return the required test JSON")
    return {"ok": True, "status": "ready", "provider": config.name, "model": config.model,
            "message": "连接成功，已验证模型返回文本 JSON；未测试图片识别。", "runtime": runtime}
