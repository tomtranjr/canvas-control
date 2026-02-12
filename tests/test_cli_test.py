from __future__ import annotations

from typer.testing import CliRunner

from canvasctl.cli import app
from canvasctl.config import AppConfig


class FakeClient:
    def get_json(self, path_or_url: str):
        assert path_or_url == "users/self/profile"
        return {"name": "Test User", "login_id": "test@example.edu"}


def test_test_command_runs_connectivity_check(monkeypatch):
    runner = CliRunner()

    monkeypatch.setattr("canvasctl.cli._load_config_or_fail", lambda: AppConfig(base_url="https://canvas.test"))
    monkeypatch.setattr("canvasctl.cli._resolve_base_url_or_fail", lambda _cfg, _override: "https://canvas.test")
    monkeypatch.setattr("canvasctl.cli._run_with_client", lambda _base_url, action: action(FakeClient()))

    result = runner.invoke(app, ["test"])

    assert result.exit_code == 0
    assert "Canvas connectivity test" in result.output
    assert "API access" in result.output
    assert "OK (200)" in result.output
    assert "Connectivity test passed" in result.output


def test_test_command_passes_base_url_override(monkeypatch):
    runner = CliRunner()
    captured: dict[str, str] = {}

    monkeypatch.setattr("canvasctl.cli._load_config_or_fail", lambda: AppConfig(base_url="https://canvas.test"))

    def fake_resolve(_cfg, override):
        captured["override"] = override
        return "https://override.test"

    def fake_run(base_url: str, action):
        captured["base_url"] = base_url
        return action(FakeClient())

    monkeypatch.setattr("canvasctl.cli._resolve_base_url_or_fail", fake_resolve)
    monkeypatch.setattr("canvasctl.cli._run_with_client", fake_run)

    result = runner.invoke(app, ["test", "--base-url", "https://override.test"])

    assert result.exit_code == 0
    assert captured == {
        "override": "https://override.test",
        "base_url": "https://override.test",
    }
