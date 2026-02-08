from __future__ import annotations

import json

from typer.testing import CliRunner

from canvasctl.canvas_api import AssignmentGrade, CourseGrade
from canvasctl.cli import app
from canvasctl.config import AppConfig


class FakeClient:
    def list_courses_with_grades(self, *, include_all: bool):
        assert include_all is False
        return [
            CourseGrade(
                course_id=100,
                course_code="BIO101",
                course_name="Biology",
                current_score=92.5,
                current_grade="A-",
            ),
            CourseGrade(
                course_id=200,
                course_code="MATH201",
                course_name="Calculus",
                current_score=87.0,
                current_grade="B+",
            ),
        ]

    def list_assignment_grades(self, course_id: int):
        return [
            AssignmentGrade(
                assignment_id=10,
                assignment_name="Homework 1",
                course_id=course_id,
                points_possible=100.0,
                score=95.0,
                grade="A",
                submitted_at="2025-01-15T10:00:00Z",
                workflow_state="graded",
            ),
            AssignmentGrade(
                assignment_id=11,
                assignment_name="Midterm",
                course_id=course_id,
                points_possible=200.0,
                score=170.0,
                grade="B+",
                submitted_at="2025-02-10T14:00:00Z",
                workflow_state="graded",
            ),
        ]


class FakeClientAll:
    """FakeClient that expects include_all=True."""

    def list_courses_with_grades(self, *, include_all: bool):
        assert include_all is True
        return [
            CourseGrade(
                course_id=100,
                course_code="BIO101",
                course_name="Biology",
                current_score=92.5,
                current_grade="A-",
            ),
        ]


def _patch(monkeypatch, fake_client=None):
    if fake_client is None:
        fake_client = FakeClient()
    monkeypatch.setattr(
        "canvasctl.cli._load_config_or_fail",
        lambda: AppConfig(base_url="https://canvas.test"),
    )
    monkeypatch.setattr(
        "canvasctl.cli._resolve_base_url_or_fail",
        lambda _cfg, _override: "https://canvas.test",
    )
    monkeypatch.setattr(
        "canvasctl.cli._run_with_client",
        lambda _base_url, action: action(fake_client),
    )


def test_grades_summary_json(monkeypatch):
    runner = CliRunner()
    _patch(monkeypatch)

    result = runner.invoke(app, ["grades", "summary", "--json"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert len(parsed) == 2
    assert parsed[0]["course_code"] == "BIO101"
    assert parsed[0]["current_score"] == 92.5
    assert parsed[0]["current_grade"] == "A-"
    assert parsed[1]["course_code"] == "MATH201"


def test_grades_summary_table(monkeypatch):
    runner = CliRunner()
    _patch(monkeypatch)

    result = runner.invoke(app, ["grades", "summary"])

    assert result.exit_code == 0
    assert "BIO101" in result.output
    assert "Biology" in result.output
    assert "A-" in result.output
    assert "MATH201" in result.output


def test_grades_summary_all(monkeypatch):
    runner = CliRunner()
    _patch(monkeypatch, fake_client=FakeClientAll())

    result = runner.invoke(app, ["grades", "summary", "--all"])

    assert result.exit_code == 0


def test_grades_summary_detailed_json(monkeypatch):
    runner = CliRunner()
    _patch(monkeypatch)

    result = runner.invoke(app, ["grades", "summary", "--detailed", "--json"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert len(parsed) == 2
    assert "course" in parsed[0]
    assert "assignments" in parsed[0]
    assert parsed[0]["course"]["course_code"] == "BIO101"
    assert len(parsed[0]["assignments"]) == 2
    assert parsed[0]["assignments"][0]["assignment_name"] == "Homework 1"


def test_grades_summary_detailed_table(monkeypatch):
    runner = CliRunner()
    _patch(monkeypatch)

    result = runner.invoke(app, ["grades", "summary", "--detailed"])

    assert result.exit_code == 0
    assert "Homework 1" in result.output
    assert "Midterm" in result.output
    assert "OVERALL" in result.output


def test_grades_summary_course_filter(monkeypatch):
    runner = CliRunner()
    _patch(monkeypatch)

    result = runner.invoke(app, ["grades", "summary", "--json", "--course", "100"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert len(parsed) == 1
    assert parsed[0]["course_id"] == 100
