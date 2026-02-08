from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

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


def _default_export_dir() -> Path:
    """Return the user's Downloads folder as the default export location."""
    return Path.home() / "Downloads"


def export_grades_csv(
    grades: list[CourseGrade],
    assignments_by_course: dict[int, list[AssignmentGrade]] | None,
    dest: Path,
) -> Path:
    """Export grades to a CSV file and return the written path."""
    dest.parent.mkdir(parents=True, exist_ok=True)

    with dest.open("w", newline="", encoding="utf-8") as fh:
        if assignments_by_course is None:
            writer = csv.writer(fh)
            writer.writerow(
                ["course_id", "course_code", "course_name", "letter_grade", "score"]
            )
            for g in grades:
                writer.writerow(
                    [
                        g.course_id,
                        g.course_code,
                        g.course_name,
                        g.current_grade or "",
                        g.current_score if g.current_score is not None else "",
                    ]
                )
        else:
            writer = csv.writer(fh)
            writer.writerow(
                [
                    "course_id",
                    "course_code",
                    "course_name",
                    "assignment_id",
                    "assignment_name",
                    "score",
                    "points_possible",
                    "grade",
                    "status",
                    "submitted_at",
                    "course_letter_grade",
                    "course_score",
                ]
            )
            for g in grades:
                course_assignments = assignments_by_course.get(g.course_id, [])
                for ag in course_assignments:
                    writer.writerow(
                        [
                            g.course_id,
                            g.course_code,
                            g.course_name,
                            ag.assignment_id,
                            ag.assignment_name,
                            ag.score if ag.score is not None else "",
                            ag.points_possible if ag.points_possible is not None else "",
                            ag.grade or "",
                            ag.workflow_state or "",
                            ag.submitted_at or "",
                            g.current_grade or "",
                            g.current_score if g.current_score is not None else "",
                        ]
                    )

    return dest


def export_grades_json(
    grades: list[CourseGrade],
    assignments_by_course: dict[int, list[AssignmentGrade]] | None,
    dest: Path,
) -> Path:
    """Export grades to a JSON file and return the written path."""
    dest.parent.mkdir(parents=True, exist_ok=True)

    if assignments_by_course is None:
        payload = [grade_to_dict(g) for g in grades]
    else:
        payload = []
        for g in grades:
            course_assignments = assignments_by_course.get(g.course_id, [])
            payload.append(
                {
                    "course": grade_to_dict(g),
                    "assignments": [
                        assignment_grade_to_dict(a) for a in course_assignments
                    ],
                }
            )

    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return dest
