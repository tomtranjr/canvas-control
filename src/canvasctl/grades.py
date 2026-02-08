from __future__ import annotations

from dataclasses import asdict

from rich.table import Table

from canvasctl.canvas_api import AssignmentGrade, CourseGrade


def grade_to_dict(grade: CourseGrade) -> dict[str, str | int | float | None]:
    return asdict(grade)


def assignment_grade_to_dict(grade: AssignmentGrade) -> dict[str, str | int | float | None]:
    return asdict(grade)


def sort_grades(grades: list[CourseGrade]) -> list[CourseGrade]:
    return sorted(
        grades,
        key=lambda g: (g.course_code.lower(), g.course_name.lower(), g.course_id),
    )


def sort_assignment_grades(grades: list[AssignmentGrade]) -> list[AssignmentGrade]:
    return sorted(
        grades,
        key=lambda g: (g.assignment_name.lower(), g.assignment_id),
    )


def render_grades_summary_table(grades: list[CourseGrade]) -> Table:
    table = Table(title="Course Grades")
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("Course Code", style="magenta")
    table.add_column("Course Name", style="bold")
    table.add_column("Letter Grade", justify="center")
    table.add_column("Score (%)", justify="right")

    for grade in grades:
        score_str = f"{grade.current_score:.1f}" if grade.current_score is not None else "N/A"
        letter_str = grade.current_grade or "N/A"
        table.add_row(
            str(grade.course_id),
            grade.course_code,
            grade.course_name,
            letter_str,
            score_str,
        )

    return table


def render_detailed_grades_table(
    course_grade: CourseGrade,
    assignment_grades: list[AssignmentGrade],
) -> Table:
    title = f"Grades: {course_grade.course_code} - {course_grade.course_name}"
    table = Table(title=title)
    table.add_column("Assignment", style="bold")
    table.add_column("Score", justify="right")
    table.add_column("Possible", justify="right")
    table.add_column("Grade")
    table.add_column("Status")

    for ag in assignment_grades:
        score_str = str(ag.score) if ag.score is not None else "-"
        possible_str = str(ag.points_possible) if ag.points_possible is not None else "-"
        grade_str = ag.grade or "-"
        status_str = ag.workflow_state or "-"
        table.add_row(
            ag.assignment_name,
            score_str,
            possible_str,
            grade_str,
            status_str,
        )

    overall_letter = course_grade.current_grade or "N/A"
    overall_score = (
        f"{course_grade.current_score:.1f}%"
        if course_grade.current_score is not None
        else "N/A"
    )
    table.add_section()
    table.add_row(
        "OVERALL",
        overall_score,
        "",
        overall_letter,
        "",
        style="bold green",
    )

    return table
