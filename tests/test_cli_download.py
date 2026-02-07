from __future__ import annotations

from typer.testing import CliRunner

from canvasctl.canvas_api import CourseSummary
from canvasctl.cli import app
from canvasctl.config import AppConfig


class FakeClient:
    def list_courses(self, *, include_all: bool):
        assert include_all is True
        return [
            CourseSummary(
                id=1631791,
                course_code="MSDS-697-01",
                name="Distributed Data Systems",
                workflow_state="available",
                term_name="Spring 2026",
                start_at=None,
                end_at=None,
            )
        ]


def _setup_common(monkeypatch, capture: dict[str, object]) -> None:
    monkeypatch.setattr("canvasctl.cli._load_config_or_fail", lambda: AppConfig(base_url="https://canvas.test"))
    monkeypatch.setattr("canvasctl.cli._resolve_base_url_or_fail", lambda _cfg, _override: "https://canvas.test")
    monkeypatch.setattr("canvasctl.cli._run_with_client", lambda _base_url, action: action(FakeClient()))

    def fake_download_for_courses(**kwargs):
        capture.update(kwargs)
        return 0

    monkeypatch.setattr("canvasctl.cli._download_for_courses", fake_download_for_courses)


def test_download_run_default_overwrite_false(monkeypatch):
    runner = CliRunner()
    capture: dict[str, object] = {}
    _setup_common(monkeypatch, capture)

    result = runner.invoke(app, ["download", "run", "--course", "1631791"])

    assert result.exit_code == 0
    assert capture["force"] is False


def test_download_run_overwrite_true(monkeypatch):
    runner = CliRunner()
    capture: dict[str, object] = {}
    _setup_common(monkeypatch, capture)

    result = runner.invoke(
        app,
        ["download", "run", "--course", "1631791", "--overwrite", "true"],
    )

    assert result.exit_code == 0
    assert capture["force"] is True


def test_download_run_overwrite_false(monkeypatch):
    runner = CliRunner()
    capture: dict[str, object] = {}
    _setup_common(monkeypatch, capture)

    result = runner.invoke(
        app,
        ["download", "run", "--course", "1631791", "--overwrite=false"],
    )

    assert result.exit_code == 0
    assert capture["force"] is False


def test_download_run_force_conflicts_with_overwrite_false(monkeypatch):
    runner = CliRunner()
    capture: dict[str, object] = {}
    _setup_common(monkeypatch, capture)

    result = runner.invoke(
        app,
        ["download", "run", "--course", "1631791", "--force", "--overwrite", "false"],
    )

    assert result.exit_code != 0
    assert "Conflicting options" in result.output
