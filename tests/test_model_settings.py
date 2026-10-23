"""Model settings tests use temporary profiles, never a user's real settings."""
import copy
from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mechanical_app.model_settings import SettingsError, SettingsStore, normalize_base_url


KEY = "test-secret-api-key-not-a-real-credential"


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = SettingsStore(Path(self.directory.name) / "private" / "settings.json")

    def payload(self):
        public = self.store.public()
        public["profiles"][0]["api_key"] = KEY
        return public

    def test_defaults_are_deepseek_and_codex_without_exposing_keys(self):
        value = self.store.public()
        self.assertEqual(value["active_profile_id"], "deepseek")
        self.assertEqual(value["profiles"][0]["model"], "deepseek-flash")
        self.assertTrue(value["profiles"][0]["vision"])
        self.assertFalse(value["profiles"][0]["has_api_key"])
        self.assertFalse(self.store.path.exists())
        self.assertEqual(self.store.snapshot().api_key, "")

    def test_write_only_encrypted_key_blank_preserves_and_clear_removes(self):
        with patch("mechanical_app.model_settings._protect_secret", return_value="encrypted-dummy") as protect:
            public = self.store.save(self.payload())
            self.assertNotIn(KEY, self.store.path.read_text(encoding="utf-8"))
            self.assertNotIn("encrypted-dummy", json.dumps(public))
            self.assertNotIn('"api_key"', json.dumps(public))
            payload = copy.deepcopy(public)
            payload["profiles"][0]["api_key"] = ""
            payload["profiles"][0]["model"] = "another-model"
            self.store.save(payload)
            self.assertEqual(protect.call_count, 1)
            self.assertEqual(json.loads(self.store.path.read_text())["profiles"][0]["api_key_encrypted"], "encrypted-dummy")
            payload["profiles"][0]["clear_api_key"] = True
            public = self.store.save(payload)
            self.assertFalse(public["profiles"][0]["has_api_key"])

    def test_public_does_not_need_to_unlock_key_and_snapshot_is_immutable(self):
        with patch("mechanical_app.model_settings._protect_secret", return_value="encrypted-dummy"):
            public = self.store.save(self.payload())
        with patch("mechanical_app.model_settings._unprotect_secret", return_value=KEY) as unlock:
            self.store.public()
            unlock.assert_not_called()
            snapshot = self.store.snapshot()
        self.assertEqual(snapshot.api_key, KEY)
        self.assertNotIn(KEY, repr(snapshot))
        with self.assertRaises(FrozenInstanceError):
            snapshot.model = "changed"
        public["active_profile_id"] = "codex"
        self.store.save(public)
        self.assertEqual(self.store.snapshot().kind, "codex")
        self.assertEqual(snapshot.profile_id, "deepseek")

    def test_invalid_save_keeps_existing_settings_and_rejects_ciphertext_input(self):
        self.store.save(self.store.public())
        original = self.store.path.read_bytes()
        for change in (
            {"base_url": "http://example.org"}, {"base_url": "https://user:password@example.org"},
            {"base_url": "https://example.org/?key=secret"}, {"vision": "true"},
            {"api_key_encrypted": "browser-ciphertext"}, {"api_key": "abc\nAuthorization: other"},
        ):
            with self.subTest(change=change):
                payload = self.store.public()
                payload["profiles"][0].update(change)
                with self.assertRaises(SettingsError):
                    self.store.save(payload)
                self.assertEqual(self.store.path.read_bytes(), original)

    def test_atomic_replace_failure_keeps_existing_settings_and_cleans_temp_file(self):
        self.store.save(self.store.public())
        original = self.store.path.read_bytes()
        with patch("mechanical_app.model_settings.os.replace", side_effect=OSError("simulated failure")):
            with self.assertRaisesRegex(SettingsError, "Could not save"):
                self.store.save(self.store.public())
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertEqual(list(self.store.path.parent.glob("*.tmp")), [])

    def test_endpoint_validation_allows_only_https_or_literal_loopback_http(self):
        for value in ("https://example.org/v1/", "http://localhost:1234/v1", "http://127.0.0.1:8000", "http://[::1]:8000/v1"):
            self.assertEqual(normalize_base_url(value), value.rstrip("/"))
        for value in ("http://example.org", "file:///tmp/model", "https://user@example.org", "https://example.org/#", "https://example.org/?", "https://example.org\\@evil.example", "https://example.org\n", "https://example.org:0", "http://localhost.evil.org", "https://example.org/../secret"):
            with self.subTest(value=value), self.assertRaises(SettingsError):
                normalize_base_url(value)

    @unittest.skipUnless(os.name == "nt", "Windows user DPAPI integration")
    def test_windows_dpapi_and_private_atomic_file_round_trip(self):
        public = self.store.save(self.payload())
        self.assertTrue(public["profiles"][0]["has_api_key"])
        self.assertNotIn(KEY, self.store.path.read_text(encoding="utf-8"))
        self.assertEqual(SettingsStore(self.store.path).snapshot().api_key, KEY)


if __name__ == "__main__":
    unittest.main()
