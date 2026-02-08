from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from canvasctl.canvas_api import CourseSummary
from canvasctl.sources import ALL_SOURCES


@dataclass(slots=True)
class InteractiveSelection:
    course_ids: list[int]
    sources: list[str]


def _load_questionary() -> Any:
    try:
        import questionary
    except ImportError as exc:  # pragma: no cover - dependency included in project deps
        raise RuntimeError(
            "Interactive mode requires questionary. Install project dependencies first."
        ) from exc
    return questionary


def prompt_interactive_selection(courses: list[CourseSummary]) -> InteractiveSelection:
    questionary = _load_questionary()

    course_choices = [
        questionary.Choice(
            title=f"{course.course_code or '[no-code]'} | {course.name} ({course.id})",
            value=course.id,
            checked=True,
        )
        for course in courses
    ]
    selected_course_ids = questionary.checkbox(
        "Select courses:",
        choices=course_choices,
    ).ask()

    if not selected_course_ids:
        raise RuntimeError("No courses selected.")

    source_choices = [
        questionary.Choice(title=source, value=source, checked=True)
        for source in ALL_SOURCES
    ]
    selected_sources = questionary.checkbox(
        "Select source types:",
        choices=source_choices,
    ).ask()

    if not selected_sources:
        raise RuntimeError("No source types selected.")

    return InteractiveSelection(
        course_ids=list(selected_course_ids),
        sources=list(selected_sources),
    )
