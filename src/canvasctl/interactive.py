from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from canvasctl.canvas_api import CourseSummary, RemoteFile
from canvasctl.sources import ALL_SOURCES


@dataclass(slots=True)
class InteractiveSelection:
    course_ids: list[int]
    sources: list[str]
    granularity: str


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

    granularity_choice = questionary.select(
        "Choose selection granularity:",
        choices=[
            questionary.Choice(title="Course-level (all files)", value="course"),
            questionary.Choice(title="Folder/file-level", value="file"),
        ],
    ).ask()

    return InteractiveSelection(
        course_ids=list(selected_course_ids),
        sources=list(selected_sources),
        granularity=granularity_choice,
    )


def prompt_file_selection(
    *,
    course: CourseSummary,
    remote_files: list[RemoteFile],
) -> set[int]:
    questionary = _load_questionary()

    folders = sorted({remote_file.folder_path or "/" for remote_file in remote_files})
    folder_choices = [
        questionary.Choice(title=folder, value=folder, checked=True) for folder in folders
    ]
    chosen_folders = questionary.checkbox(
        f"{course.name}: choose folders",
        choices=folder_choices,
    ).ask()

    if not chosen_folders:
        return set()

    file_choices = []
    for remote_file in remote_files:
        folder = remote_file.folder_path or "/"
        if folder not in chosen_folders:
            continue
        label = f"[{folder}] {remote_file.filename} (id={remote_file.file_id}, {remote_file.source_type})"
        file_choices.append(
            questionary.Choice(title=label, value=remote_file.file_id, checked=True)
        )

    selected_file_ids = questionary.checkbox(
        f"{course.name}: choose files",
        choices=file_choices,
    ).ask()

    return set(selected_file_ids or [])
