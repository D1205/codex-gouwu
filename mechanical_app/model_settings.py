"""Local model profiles. API keys are write-only and encrypted for the Windows user."""
from __future__ import annotations

import base64
import ctypes
from dataclasses import dataclass, field
import ipaddress
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any
from urllib.parse import urlsplit, urlunsplit


VERSION = 1
MAX_SETTINGS_BYTES = 1024 * 1024
_PROFILE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_ENTROPY = b"CodexGouwu/model-settings/v1"
_PRESETS = (
    {"id": "deepseek", "name": "DeepSeek", "kind": "openai_compatible", "preset": "deepseek",
     "base_url": "https://api.deepseek.com", "model": "deepseek-flash", "vision": True},
    {"id": "codex", "name": "Codex CLI", "kind": "codex", "preset": "codex",
     "base_url": "", "model": "", "vision": True},
    {"id": "custom", "name": "OpenAI compatible", "kind": "openai_compatible", "preset": "custom",
     "base_url": "https://api.openai.com/v1", "model": "", "vision": False},
)


class SettingsError(ValueError):
    """Safe to display; messages contain no stored values or encryption material."""


@dataclass(frozen=True)
class ModelConfig:
    kind: str
    profile_id: str
    name: str
    base_url: str
    model: str
    vision: bool
    api_key: str = field(default="", repr=False)
    preset: str = "custom"


def normalize_base_url(value: Any) -> str:
    """HTTPS is mandatory except for explicit loopback development servers."""
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise SettingsError("Model base URL must be a nonempty URL of at most 2048 characters")
    if any(ord(character) <= 32 or ord(character) == 127 for character in value) or "\\" in value:
        raise SettingsError("Model base URL contains invalid characters")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
        if not hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            raise ValueError
        # Reject even empty URL query/fragment delimiters so endpoints stay unambiguous.
        if "?" in value or "#" in value or port == 0:
            raise ValueError
        try:
            loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            loopback = hostname.lower() == "localhost"
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            raise ValueError
        if any(part in {".", ".."} for part in parsed.path.split("/")):
            raise ValueError
    except (ValueError, UnicodeError):
        raise SettingsError("Model base URL requires HTTPS (HTTP is allowed only for loopback), without credentials, query or fragment") from None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _dpapi(data: bytes, *, decrypt: bool) -> bytes:
    """Use current-user DPAPI; never fall back to plaintext on another platform."""
    if os.name != "nt":
        raise SettingsError("Saving API keys requires Windows current-user encryption")
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    def blob(value: bytes) -> tuple[Blob, Any]:
        buffer = ctypes.create_string_buffer(value)
        return Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer

    incoming, incoming_buffer = blob(data)
    entropy, entropy_buffer = blob(_ENTROPY)
    outgoing = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        function = crypt.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p,
                             ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        arguments = (ctypes.byref(incoming), None, ctypes.byref(entropy), None, None, 1, ctypes.byref(outgoing))
    else:
        function = crypt.CryptProtectData
        function.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.POINTER(Blob), ctypes.c_void_p,
                             ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        arguments = (ctypes.byref(incoming), "CodexGouwu API key", ctypes.byref(entropy), None, None, 1, ctypes.byref(outgoing))
    function.restype = wintypes.BOOL
    if not function(*arguments):
        raise SettingsError("Windows could not unlock the saved API key" if decrypt else "Windows could not encrypt the API key")
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        kernel.LocalFree(ctypes.cast(outgoing.pbData, ctypes.c_void_p))


def _protect_secret(value: str) -> str:
    return base64.b64encode(_dpapi(value.encode("utf-8"), decrypt=False)).decode("ascii")


def _unprotect_secret(value: str) -> str:
    try:
        return _dpapi(base64.b64decode(value, validate=True), decrypt=True).decode("utf-8")
    except (ValueError, UnicodeError):
        raise SettingsError("The saved API key cannot be unlocked; enter it again") from None


def _restrict(path: Path) -> None:
    """Protect the file before writing; Windows chmod alone does not restrict reads."""
    if os.name != "nt":
        path.chmod(0o700 if path.is_dir() else 0o600)
        return
    from ctypes import wintypes
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    descriptor = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    present, defaulted = wintypes.BOOL(), wintypes.BOOL()
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    convert.restype = wintypes.BOOL
    get_dacl = advapi.GetSecurityDescriptorDacl
    get_dacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    get_dacl.restype = wintypes.BOOL
    set_info = advapi.SetNamedSecurityInfoW
    set_info.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    set_info.restype = wintypes.DWORD
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    # OWNER RIGHTS identifies the owner of each new atomic file; SYSTEM retains access.
    if not convert("D:P(A;;FA;;;OW)(A;;FA;;;SY)", 1, ctypes.byref(descriptor), None):
        raise SettingsError("Could not restrict settings file permissions")
    try:
        if not get_dacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
            raise SettingsError("Could not restrict settings file permissions")
        if set_info(str(path), 1, 0x80000004, None, None, dacl, None):
            raise SettingsError("Could not restrict settings file permissions")
    finally:
        kernel.LocalFree(descriptor)


def _text(value: Any, label: str, limit: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise SettingsError(f"Invalid model profile {label}")
    return value.strip()


def _defaults() -> dict[str, Any]:
    return {"version": VERSION, "active_profile_id": "deepseek", "profiles": [dict(item, api_key_encrypted="") for item in _PRESETS[:2]]}


class SettingsStore:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "CodexGouwu" / "settings.json"
        self._lock = threading.RLock()

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return _defaults()
        try:
            if self.path.is_symlink() or self.path.stat().st_size > MAX_SETTINGS_BYTES:
                raise ValueError
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("version") != VERSION:
                raise ValueError
            return self._validate(value, previous={}, loading=True)
        except (OSError, ValueError, TypeError, KeyError):
            raise SettingsError("Saved model settings are invalid or unreadable") from None

    def _validate(self, payload: Any, previous: dict[str, Any], *, loading: bool = False) -> dict[str, Any]:
        if not isinstance(payload, dict) or ("version" in payload and (type(payload["version"]) is not int or payload["version"] != VERSION)):
            raise SettingsError("Unsupported model settings format")
        profiles = payload.get("profiles")
        if not isinstance(profiles, list) or not 1 <= len(profiles) <= 20:
            raise SettingsError("Settings require between one and twenty model profiles")
        old_profiles = {item["id"]: item for item in previous.get("profiles", [])}
        result, seen = [], set()
        for profile in profiles:
            if not isinstance(profile, dict):
                raise SettingsError("Invalid model profile")
            identifier = profile.get("id")
            if not isinstance(identifier, str) or not _PROFILE_ID.fullmatch(identifier) or identifier in seen:
                raise SettingsError("Model profile identifiers must be unique ASCII identifiers")
            seen.add(identifier)
            kind = profile.get("kind")
            if not isinstance(kind, str) or kind not in {"codex", "openai_compatible"}:
                raise SettingsError("Unsupported model provider kind")
            preset = profile.get("preset", "codex" if kind == "codex" else "custom")
            if not isinstance(preset, str) or preset not in {"deepseek", "custom", "codex"} or ((kind == "codex") != (preset == "codex")):
                raise SettingsError("Invalid model provider preset")
            name = _text(profile.get("name"), "name", 120)
            model = _text(profile.get("model", ""), "model", 200, empty=kind == "codex")
            base_url = normalize_base_url(profile.get("base_url")) if kind != "codex" else ""
            vision = profile.get("vision", False)
            if type(vision) is not bool:
                raise SettingsError("Model vision capability must be true or false")
            encrypted = profile.get("api_key_encrypted", "") if loading else old_profiles.get(identifier, {}).get("api_key_encrypted", "")
            if not isinstance(encrypted, str) or len(encrypted) > 32768:
                raise SettingsError("Invalid saved API key")
            if loading:
                if "api_key" in profile:
                    raise SettingsError("Plaintext API keys are not a supported storage format")
            else:
                if "api_key_encrypted" in profile:
                    raise SettingsError("Encrypted API keys cannot be supplied by the browser")
                clear = profile.get("clear_api_key", False)
                if type(clear) is not bool:
                    raise SettingsError("Invalid clear API key flag")
                key = _text(profile.get("api_key", ""), "API key", 8192, empty=True)
                if clear and key:
                    raise SettingsError("Enter a new API key or clear the saved key, not both")
                if clear:
                    encrypted = ""
                elif key:
                    encrypted = _protect_secret(key)
            if kind == "codex":
                encrypted = ""
            result.append({"id": identifier, "name": name, "kind": kind, "preset": preset,
                           "base_url": base_url, "model": model, "vision": vision, "api_key_encrypted": encrypted})
        active = payload.get("active_profile_id")
        if not isinstance(active, str) or active not in seen:
            raise SettingsError("The active model profile must exist")
        return {"version": VERSION, "active_profile_id": active, "profiles": result}

    @staticmethod
    def _public(value: dict[str, Any]) -> dict[str, Any]:
        return {"version": VERSION, "active_profile_id": value["active_profile_id"],
                "profiles": [{key: item[key] for key in ("id", "name", "kind", "preset", "base_url", "model", "vision")} | {"has_api_key": bool(item["api_key_encrypted"])} for item in value["profiles"]],
                "presets": [dict(item) for item in _PRESETS]}

    def public(self) -> dict[str, Any]:
        with self._lock:
            return self._public(self._read())

    def save(self, payload: Any) -> dict[str, Any]:
        with self._lock:
            value = self._validate(payload, self._read())
            serialized = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
            if len(serialized) > MAX_SETTINGS_BYTES:
                raise SettingsError("Model settings exceed the storage limit")
            created_parent = not self.path.parent.exists()
            temporary = None
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                if created_parent:
                    _restrict(self.path.parent)
                descriptor, temporary = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
                with os.fdopen(descriptor, "wb") as stream:
                    _restrict(Path(temporary))
                    stream.write(serialized)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                return self._public(value)
            except OSError:
                raise SettingsError("Could not save model settings") from None
            finally:
                if temporary is not None:
                    Path(temporary).unlink(missing_ok=True)

    def snapshot(self) -> ModelConfig:
        with self._lock:
            value = self._read()
            profile = next(item for item in value["profiles"] if item["id"] == value["active_profile_id"])
            secret = _unprotect_secret(profile["api_key_encrypted"]) if profile["api_key_encrypted"] else ""
            return ModelConfig(kind=profile["kind"], profile_id=profile["id"], name=profile["name"],
                               base_url=profile["base_url"], model=profile["model"], vision=profile["vision"],
                               api_key=secret, preset=profile["preset"])
