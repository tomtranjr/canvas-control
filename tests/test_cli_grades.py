from __future__ import annotations

import csv
import json
from pathlib import Path

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


def test_grades_export_csv_default(monkeypatch, tmp_path):
    runner = CliRunner()
    _patch(monkeypatch)
    monkeypatch.setattr("canvasctl.cli._default_export_dir", lambda: tmp_path)

    result = runner.invoke(app, ["grades", "export"])

    assert result.exit_code == 0
    csv_file = tmp_path / "canvasctl-grades.csv"
    assert csv_file.exists()
    with csv_file.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == ["course_id", "course_code", "course_name", "letter_grade", "score"]
    assert len(rows) == 3  # header + 2 courses


def test_grades_export_json(monkeypatch, tmp_path):
    runner = CliRunner()
    _patch(monkeypatch)
    monkeypatch.setattr("canvasctl.cli._default_export_dir", lambda: tmp_path)

    result = runner.invoke(app, ["grades", "export", "--format", "json"])

    assert result.exit_code == 0
    json_file = tmp_path / "canvasctl-grades.json"
    assert json_file.exists()
    parsed = json.loads(json_file.read_text(encoding="utf-8"))
    assert len(parsed) == 2
    assert parsed[0]["course_code"] == "BIO101"


def test_grades_export_detailed_csv(monkeypatch, tmp_path):
    runner = CliRunner()
    _patch(monkeypatch)
    monkeypatch.setattr("canvasctl.cli._default_export_dir", lambda: tmp_path)

    result = runner.invoke(app, ["grades", "export", "--detailed"])

    assert result.exit_code == 0
    csv_file = tmp_path / "canvasctl-grades.csv"
    assert csv_file.exists()
    with csv_file.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[0][3] == "assignment_id"
    assert rows[0][4] == "assignment_name"
    # 2 courses * 2 assignments each = 4 data rows + header
    assert len(rows) == 5


def test_grades_export_custom_dest(monkeypatch, tmp_path):
    runner = CliRunner()
    _patch(monkeypatch)
    custom_dir = tmp_path / "my-exports"
    custom_dir.mkdir()

    result = runner.invoke(app, ["grades", "export", "--dest", str(custom_dir)])

    assert result.exit_code == 0
    csv_file = custom_dir / "canvasctl-grades.csv"
    assert csv_file.exists()


def test_grades_export_course_filter(monkeypatch, tmp_path):
    runner = CliRunner()
    _patch(monkeypatch)
    monkeypatch.setattr("canvasctl.cli._default_export_dir", lambda: tmp_path)

    result = runner.invoke(
        app, ["grades", "export", "--format", "json", "--course", "100"]
    )

    assert result.exit_code == 0
    json_file = tmp_path / "canvasctl-grades.json"
    parsed = json.loads(json_file.read_text(encoding="utf-8"))
    assert len(parsed) == 1
    assert parsed[0]["course_id"] == 100
