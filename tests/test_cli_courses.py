from __future__ import annotations

import json

from typer.testing import CliRunner

from canvasctl.canvas_api import CourseSummary
from canvasctl.cli import app
from canvasctl.config import AppConfig


class FakeClient:
    def list_courses(self, *, include_all: bool):
        assert include_all is False
        return [
            CourseSummary(
                id=100,
                course_code="BIO101",
                name="Biology",
                workflow_state="available",
                term_name="Spring",
                start_at=None,
                end_at=None,
            )
        ]


class FakeClientWithWhitespace:
    def list_courses(self, *, include_all: bool):
        assert include_all is False
        return [
            CourseSummary(
                id=101,
                course_code=" MSDS Linear Algebra Requirement 2025",
                name=" MSDS Linear Algebra Requirement 2025",
                workflow_state="available",
                term_name="Default Term",
                start_at=None,
                end_at=None,
            )
        ]


def test_courses_list_json(monkeypatch):
    runner = CliRunner()

    monkeypatch.setattr("canvasctl.cli._load_config_or_fail", lambda: AppConfig(base_url="https://canvas.test"))
    monkeypatch.setattr("canvasctl.cli._resolve_base_url_or_fail", lambda _cfg, _override: "https://canvas.test")
    monkeypatch.setattr("canvasctl.cli._run_with_client", lambda _base_url, action: action(FakeClient()))

    result = runner.invoke(app, ["courses", "list", "--json"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed[0]["id"] == 100
    assert parsed[0]["course_code"] == "BIO101"


def test_courses_list_table(monkeypatch):
    runner = CliRunner()

    monkeypatch.setattr("canvasctl.cli._load_config_or_fail", lambda: AppConfig(base_url="https://canvas.test"))
    monkeypatch.setattr("canvasctl.cli._resolve_base_url_or_fail", lambda _cfg, _override: "https://canvas.test")
    monkeypatch.setattr("canvasctl.cli._run_with_client", lambda _base_url, action: action(FakeClient()))

    result = runner.invoke(app, ["courses", "list"])

    assert result.exit_code == 0
    assert "BIO101" in result.output
    assert "Biology" in result.output


def test_courses_list_table_trims_leading_whitespace(monkeypatch):
    runner = CliRunner()

    monkeypatch.setattr("canvasctl.cli._load_config_or_fail", lambda: AppConfig(base_url="https://canvas.test"))
    monkeypatch.setattr("canvasctl.cli._resolve_base_url_or_fail", lambda _cfg, _override: "https://canvas.test")
    monkeypatch.setattr("canvasctl.cli._run_with_client", lambda _base_url, action: action(FakeClientWithWhitespace()))

    result = runner.invoke(app, ["courses", "list"])

    assert result.exit_code == 0
    assert "│  MSDS Linear" not in result.output
    assert "│ MSDS Linear" in result.output
