from __future__ import annotations

import csv
import json

from canvasctl.canvas_api import AssignmentGrade, CourseGrade
from canvasctl.grades import (
    assignment_grade_to_dict,
    export_grades_csv,
    export_grades_json,
    grade_to_dict,
    render_detailed_grades_table,
    render_grades_summary_table,
    sort_assignment_grades,
    sort_grades,
)


def _make_course_grade(**overrides) -> CourseGrade:
    defaults = {
        "course_id": 1,
        "course_code": "BIO101",
        "course_name": "Biology",
        "current_score": 92.5,
        "current_grade": "A-",
    }
    defaults.update(overrides)
    return CourseGrade(**defaults)


def _make_assignment_grade(**overrides) -> AssignmentGrade:
    defaults = {
        "assignment_id": 10,
        "assignment_name": "Homework 1",
        "course_id": 1,
        "points_possible": 100.0,
        "score": 95.0,
        "grade": "A",
        "submitted_at": "2025-01-15T10:00:00Z",
        "workflow_state": "graded",
    }
    defaults.update(overrides)
    return AssignmentGrade(**defaults)


def test_sort_grades_by_code_name_id():
    grades = [
        _make_course_grade(course_id=3, course_code="MATH201", course_name="Calculus"),
        _make_course_grade(course_id=1, course_code="BIO101", course_name="Biology"),
        _make_course_grade(course_id=2, course_code="BIO101", course_name="Advanced Biology"),
    ]
    sorted_grades = sort_grades(grades)
    assert [g.course_id for g in sorted_grades] == [2, 1, 3]


def test_grade_to_dict():
    grade = _make_course_grade()
    result = grade_to_dict(grade)
    assert result["course_id"] == 1
    assert result["course_code"] == "BIO101"
    assert result["course_name"] == "Biology"
    assert result["current_score"] == 92.5
    assert result["current_grade"] == "A-"


def test_assignment_grade_to_dict():
    ag = _make_assignment_grade()
    result = assignment_grade_to_dict(ag)
    assert result["assignment_id"] == 10
    assert result["assignment_name"] == "Homework 1"
    assert result["score"] == 95.0
    assert result["grade"] == "A"
    assert result["workflow_state"] == "graded"


def test_sort_assignment_grades():
    grades = [
        _make_assignment_grade(assignment_id=2, assignment_name="Quiz 1"),
        _make_assignment_grade(assignment_id=1, assignment_name="Homework 1"),
        _make_assignment_grade(assignment_id=3, assignment_name="Homework 1"),
    ]
    sorted_grades = sort_assignment_grades(grades)
    assert [g.assignment_id for g in sorted_grades] == [1, 3, 2]


def test_render_grades_summary_table_has_columns():
    grades = [_make_course_grade()]
    table = render_grades_summary_table(grades)
    column_names = [col.header for col in table.columns]
    assert "ID" in column_names
    assert "Course Code" in column_names
    assert "Course Name" in column_names
    assert "Letter Grade" in column_names
    assert "Score (%)" in column_names


def test_render_grades_summary_table_na_for_none():
    grade = _make_course_grade(current_score=None, current_grade=None)
    table = render_grades_summary_table([grade])
    # Render the table to check N/A appears
    from rich.console import Console
    from io import StringIO

    output = StringIO()
    console = Console(file=output, width=120)
    console.print(table)
    rendered = output.getvalue()
    assert "N/A" in rendered


def test_render_detailed_grades_table_includes_overall():
    course_grade = _make_course_grade()
    assignments = [_make_assignment_grade()]
    table = render_detailed_grades_table(course_grade, assignments)

    from rich.console import Console
    from io import StringIO

    output = StringIO()
    console = Console(file=output, width=120)
    console.print(table)
    rendered = output.getvalue()
    assert "OVERALL" in rendered
    assert "92.5%" in rendered
    assert "A-" in rendered


def test_render_detailed_grades_table_shows_assignments():
    course_grade = _make_course_grade()
    assignments = [
        _make_assignment_grade(assignment_name="Midterm Exam"),
        _make_assignment_grade(assignment_id=11, assignment_name="Final Paper"),
    ]
    table = render_detailed_grades_table(course_grade, assignments)

    from rich.console import Console
    from io import StringIO

    output = StringIO()
    console = Console(file=output, width=120)
    console.print(table)
    rendered = output.getvalue()
    assert "Midterm Exam" in rendered
    assert "Final Paper" in rendered


def test_export_grades_csv_summary(tmp_path):
    grades = [
        _make_course_grade(course_id=1, course_code="BIO101"),
        _make_course_grade(course_id=2, course_code="MATH201", current_score=87.0, current_grade="B+"),
    ]
    dest = tmp_path / "grades.csv"
    result = export_grades_csv(grades, None, dest)

    assert result == dest
    assert dest.exists()

    with dest.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        rows = list(reader)

    assert rows[0] == ["course_id", "course_code", "course_name", "letter_grade", "score"]
    assert rows[1][0] == "1"
    assert rows[1][1] == "BIO101"
    assert rows[1][3] == "A-"
    assert rows[2][1] == "MATH201"
    assert len(rows) == 3


def test_export_grades_csv_detailed(tmp_path):
    grades = [_make_course_grade(course_id=1)]
    assignments_by_course = {
        1: [
            _make_assignment_grade(assignment_id=10, assignment_name="Homework 1"),
            _make_assignment_grade(assignment_id=11, assignment_name="Quiz 1", score=45.0),
        ]
    }
    dest = tmp_path / "grades-detailed.csv"
    result = export_grades_csv(grades, assignments_by_course, dest)

    assert result == dest
    with dest.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        rows = list(reader)

    assert rows[0][0] == "course_id"
    assert rows[0][3] == "assignment_id"
    assert rows[0][4] == "assignment_name"
    assert len(rows) == 3  # header + 2 assignments
    assert rows[1][4] == "Homework 1"
    assert rows[2][4] == "Quiz 1"


def test_export_grades_json_summary(tmp_path):
    grades = [
        _make_course_grade(course_id=1),
        _make_course_grade(course_id=2, course_code="MATH201"),
    ]
    dest = tmp_path / "grades.json"
    result = export_grades_json(grades, None, dest)

    assert result == dest
    parsed = json.loads(dest.read_text(encoding="utf-8"))
    assert len(parsed) == 2
    assert parsed[0]["course_id"] == 1
    assert parsed[1]["course_code"] == "MATH201"


def test_export_grades_json_detailed(tmp_path):
    grades = [_make_course_grade(course_id=1)]
    assignments_by_course = {
        1: [_make_assignment_grade(assignment_id=10, assignment_name="Homework 1")]
    }
    dest = tmp_path / "grades-detailed.json"
    result = export_grades_json(grades, assignments_by_course, dest)

    assert result == dest
    parsed = json.loads(dest.read_text(encoding="utf-8"))
    assert len(parsed) == 1
    assert "course" in parsed[0]
    assert "assignments" in parsed[0]
    assert parsed[0]["course"]["course_id"] == 1
    assert parsed[0]["assignments"][0]["assignment_name"] == "Homework 1"


def test_export_creates_parent_directories(tmp_path):
    grades = [_make_course_grade()]
    dest = tmp_path / "nested" / "dir" / "grades.csv"
    result = export_grades_csv(grades, None, dest)
    assert result == dest
    assert dest.exists()
