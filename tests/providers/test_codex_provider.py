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
from rikugan.core.types import Message, Role
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

    def test_validate_key_fetches_live_models(self):
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

            with patch.object(
                CodexProvider,
                "_request",
                return_value={"models": [{"slug": "gpt-live", "display_name": "GPT Live", "visibility": "list"}]},
            ) as request:
                self.assertTrue(provider.validate_key())
                request.assert_called_once()

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


class TestCodexModels(unittest.TestCase):
    def test_fetch_models_live_uses_codex_models_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"CODEX_HOME": tmp}, clear=False):
            home = Path(tmp)
            _write_auth(home, {"access_token": "access", "refresh_token": "refresh", "account_id": "acct"})
            (home / "models_cache.json").write_text(json.dumps({"client_version": "0.133.0"}))
            provider = CodexProvider()

            with patch.object(
                CodexProvider,
                "_request",
                return_value={
                    "models": [
                        {
                            "slug": "gpt-5.5",
                            "display_name": "GPT-5.5",
                            "visibility": "list",
                            "context_window": 272000,
                            "supports_parallel_tool_calls": True,
                            "input_modalities": ["text", "image"],
                        },
                        {
                            "slug": "codex-auto-review",
                            "display_name": "Codex Auto Review",
                            "visibility": "hide",
                        },
                    ]
                },
            ) as request:
                models = provider._fetch_models_live()

        self.assertEqual([m.id for m in models], ["gpt-5.5"])
        self.assertEqual(models[0].name, "GPT-5.5")
        self.assertEqual(models[0].context_window, 272000)
        self.assertTrue(models[0].supports_tools)
        self.assertTrue(models[0].supports_vision)
        request.assert_called_once_with("GET", "models?client_version=0.133.0", None, stream=False)


class TestCodexRequestPayload(unittest.TestCase):
    def test_omits_generation_knobs_and_empty_tool_fields(self):
        provider = CodexProvider(model="gpt-5-codex")

        kwargs = provider._build_request_kwargs([Message(role=Role.USER, content="hi")], tools=None, system="")

        self.assertNotIn("temperature", kwargs)
        self.assertNotIn("max_output_tokens", kwargs)
        self.assertNotIn("tools", kwargs)
        self.assertNotIn("tool_choice", kwargs)
        self.assertNotIn("parallel_tool_calls", kwargs)
        self.assertNotIn("instructions", kwargs)

    def test_includes_tool_fields_only_with_tools(self):
        provider = CodexProvider(model="gpt-5-codex")
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "Lookup a value",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        kwargs = provider._build_request_kwargs([Message(role=Role.USER, content="hi")], tools=tools, system="sys")

        self.assertEqual(kwargs["instructions"], "sys")
        self.assertEqual(kwargs["tool_choice"], "auto")
        self.assertTrue(kwargs["parallel_tool_calls"])
        self.assertEqual(kwargs["tools"][0]["name"], "lookup")


if __name__ == "__main__":
    unittest.main()
