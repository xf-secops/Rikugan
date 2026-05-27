"""Tests for Codex OAuth auth file handling and request auth headers."""

from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rikugan.core.errors import AuthenticationError
from rikugan.providers.codex_provider import CodexProvider, _id_token_info, codex_auth_status


def _jwt(claims: dict) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8")).decode("ascii").rstrip("=")
    return f"e30.{payload}.sig"


def _write_auth(home: Path, tokens: dict, auth_mode: str = "chatgpt") -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "auth.json").write_text(
        json.dumps(
            {
                "auth_mode": auth_mode,
                "OPENAI_API_KEY": None,
                "tokens": tokens,
                "last_refresh": "2026-05-27T00:00:00Z",
            }
        )
    )


class TestCodexAuthFile(unittest.TestCase):
    def test_status_requires_managed_chatgpt_tokens_with_refresh(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"CODEX_HOME": tmp}, clear=False):
            _write_auth(Path(tmp), {"access_token": "access"})

            self.assertEqual(codex_auth_status(), ("Setup required", "error"))
            with self.assertRaises(AuthenticationError):
                CodexProvider().ensure_ready()

    def test_validate_key_uses_local_auth_without_models_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"CODEX_HOME": tmp}, clear=False):
            _write_auth(
                Path(tmp),
                {
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "id_token": "bad.jwt",
                    "account_id": "acct",
                },
            )
            provider = CodexProvider()

            with patch.object(CodexProvider, "_request", side_effect=AssertionError("unexpected network call")):
                self.assertTrue(provider.validate_key())
                self.assertEqual(
                    [m.id for m in provider._fetch_models_live()], ["gpt-5.4", "gpt-5.2-codex", "gpt-5-codex"]
                )

    def test_validate_key_rejects_missing_auth(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"CODEX_HOME": tmp}, clear=False):
            self.assertFalse(CodexProvider().validate_key())


class TestCodexHeaders(unittest.TestCase):
    def test_headers_use_codex_originator_and_account_id(self):
        id_token = _jwt(
            {
                "https://api.openai.com/auth": {
                    "chatgpt_account_id": "acct-123",
                    "chatgpt_account_is_fedramp": True,
                }
            }
        )
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"CODEX_HOME": tmp}, clear=False):
            _write_auth(Path(tmp), {"access_token": "access", "refresh_token": "refresh", "id_token": id_token})

            headers = CodexProvider()._headers()

        self.assertEqual(headers["Authorization"], "Bearer access")
        self.assertEqual(headers["originator"], "codex_cli_rs")
        self.assertTrue(headers["User-Agent"].startswith("codex_cli_rs/"))
        self.assertEqual(headers["ChatGPT-Account-ID"], "acct-123")
        self.assertEqual(headers["X-OpenAI-Fedramp"], "true")

    def test_headers_fall_back_to_access_token_account_id(self):
        access_token = _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "acct-from-access"}})
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"CODEX_HOME": tmp}, clear=False):
            _write_auth(
                Path(tmp),
                {
                    "access_token": access_token,
                    "refresh_token": "refresh",
                    "id_token": "malformed",
                },
            )

            headers = CodexProvider()._headers()

        self.assertEqual(headers["ChatGPT-Account-ID"], "acct-from-access")

    def test_malformed_jwt_payload_is_ignored(self):
        self.assertIsNone(_id_token_info("not-a-jwt")["chatgpt_account_id"])


if __name__ == "__main__":
    unittest.main()
