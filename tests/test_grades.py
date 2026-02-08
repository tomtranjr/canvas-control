from __future__ import annotations

from canvasctl.canvas_api import AssignmentGrade, CourseGrade
from canvasctl.grades import (
    assignment_grade_to_dict,
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
