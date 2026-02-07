from __future__ import annotations

from rich.console import Console

from canvasctl import auth


def test_resolve_token_prefers_env(monkeypatch):
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "env-token")

    token_info = auth.resolve_token(Console(record=True))

    assert token_info.token == "env-token"
    assert token_info.source == "env"


def test_resolve_token_prompts_when_env_missing(monkeypatch):
    monkeypatch.delenv(auth.TOKEN_ENV_VAR, raising=False)
    monkeypatch.setattr(auth.getpass, "getpass", lambda _: "prompt-token")

    token_info = auth.resolve_token(Console(record=True))

    assert token_info.token == "prompt-token"
    assert token_info.source == "prompt"
