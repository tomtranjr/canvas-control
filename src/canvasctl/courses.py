from __future__ import annotations

from dataclasses import asdict

from rich.table import Table

from canvasctl.canvas_api import CourseSummary


def course_to_dict(course: CourseSummary) -> dict[str, str | int | None]:
    return asdict(course)


def render_courses_table(courses: list[CourseSummary]) -> Table:
    table = Table(title="Canvas Courses")
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("Course Code", style="magenta")
    table.add_column("Name", style="bold")
    table.add_column("State")
    table.add_column("Term")
    table.add_column("Start")
    table.add_column("End")

    for course in courses:
        table.add_row(
            str(course.id),
            course.course_code,
            course.name,
            course.workflow_state or "",
            course.term_name or "",
            course.start_at or "",
            course.end_at or "",
        )

    return table


def sort_courses(courses: list[CourseSummary]) -> list[CourseSummary]:
    return sorted(courses, key=lambda c: ((c.course_code or "").lower(), c.name.lower(), c.id))
