from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Sequence

import typer
from rich.console import Console
from rich.table import Table

from canvasctl.auth import AuthError, TokenInfo, prompt_for_token, resolve_token
from canvasctl.canvas_api import (
    AssignmentGrade,
    CanvasApiError,
    CanvasClient,
    CanvasUnauthorizedError,
    CourseGrade,
    CourseSummary,
    RemoteFile,
)
from canvasctl.config import (
    AppConfig,
    ConfigError,
    DEFAULT_CONCURRENCY,
    clear_default_destination,
    load_config,
    resolve_base_url,
    set_base_url,
    set_default_destination,
)
from canvasctl.courses import course_to_dict, render_courses_table, sort_courses
from canvasctl.grades import (
    assignment_grade_to_dict,
    grade_to_dict,
    render_detailed_grades_table,
    render_grades_summary_table,
    sort_assignment_grades,
    sort_grades,
)
from canvasctl.downloader import (
    DownloadTask,
    build_course_slug,
    download_tasks,
    plan_course_download_tasks,
    result_to_manifest_item,
    summarize_results,
)
from canvasctl.interactive import prompt_file_selection, prompt_interactive_selection
from canvasctl.manifest import (
    course_manifest_path,
    index_items_by_file_id,
    load_manifest,
    write_course_manifest,
    write_run_summary,
)
from canvasctl.sources import (
    ALL_SOURCES,
    normalize_sources,
    warning_to_manifest_item,
    collect_remote_files_for_course,
)

app = typer.Typer(help="Canvas LMS CLI")
config_app = typer.Typer(help="Manage local cvsctl config")
courses_app = typer.Typer(help="List and inspect courses")
download_app = typer.Typer(help="Download course files")
grades_app = typer.Typer(help="View course grades")

app.add_typer(config_app, name="config")
app.add_typer(courses_app, name="courses")
app.add_typer(download_app, name="download")
app.add_typer(grades_app, name="grades")

console = Console()


class SourceChoice(str, Enum):
    files = "files"
    assignments = "assignments"
    discussions = "discussions"
    pages = "pages"
    modules = "modules"


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _fail(message: str, *, code: int = 1) -> None:
    console.print(f"[red]{message}[/red]")
    raise typer.Exit(code=code)


def _load_config_or_fail() -> AppConfig:
    try:
        return load_config()
    except ConfigError as exc:
        _fail(str(exc))
    raise AssertionError("unreachable")


def _resolve_base_url_or_fail(cfg: AppConfig, override: str | None) -> str:
    try:
        return resolve_base_url(override, cfg)
    except ConfigError as exc:
        _fail(str(exc))
    raise AssertionError("unreachable")


def _resolve_token_or_fail() -> TokenInfo:
    try:
        return resolve_token(console)
    except AuthError as exc:
        _fail(str(exc))
    raise AssertionError("unreachable")


def _run_with_client(
    base_url: str,
    action: Callable[[CanvasClient], int | None],
) -> int | None:
    token_info = _resolve_token_or_fail()

    while True:
        try:
            with CanvasClient(base_url, token_info.token) as client:
                return action(client)
        except CanvasUnauthorizedError as exc:
            if token_info.source == "env":
                _fail(
                    "Canvas rejected CANVAS_TOKEN (401). Update CANVAS_TOKEN and retry."
                )
            console.print(f"[yellow]{exc}[/yellow]")
            retry = typer.confirm("Token rejected. Re-enter token?", default=True)
            if not retry:
                _fail("Aborted after token rejection.")
            token_info = prompt_for_token(console)
        except CanvasApiError as exc:
            _fail(str(exc))


def _resolve_destination(dest: Path | None, cfg: AppConfig) -> Path:
    if dest is not None:
        return dest.expanduser().resolve()
    return cfg.destination_path().resolve()


def _resolve_concurrency(value: int | None, cfg: AppConfig) -> int:
    if value is not None:
        if value <= 0:
            _fail("--concurrency must be positive.")
        return value
    return cfg.default_concurrency if cfg.default_concurrency > 0 else DEFAULT_CONCURRENCY


def _parse_bool_text(value: str, *, option_name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False
    _fail(
        f"{option_name} must be one of: true/false, 1/0, yes/no, on/off. "
        f"Received: {value!r}"
    )
    raise AssertionError("unreachable")


def _resolve_overwrite(overwrite: str | None, force: bool) -> bool:
    if overwrite is None:
        return force
    parsed = _parse_bool_text(overwrite, option_name="--overwrite")
    if force and not parsed:
        _fail("Conflicting options: --force and --overwrite=false cannot be used together.")
    return parsed or force


def _persist_destination_if_requested(
    *,
    export_dest: bool,
    provided_dest: Path | None,
    resolved_dest: Path,
) -> None:
    if not export_dest:
        return
    if provided_dest is None:
        _fail("--export-dest requires --dest <path>.")
    try:
        cfg = set_default_destination(resolved_dest)
    except ConfigError as exc:
        _fail(str(exc))
    console.print(f"[green]Saved default download path:[/green] {cfg.default_dest}")


def _resolve_courses_from_selectors(
    courses: Sequence[CourseSummary],
    selectors: Sequence[str],
) -> list[CourseSummary]:
    by_id = {str(course.id): course for course in courses}
    by_code: dict[str, list[CourseSummary]] = {}
    for course in courses:
        code = course.course_code.strip().lower()
        if not code:
            continue
        by_code.setdefault(code, []).append(course)

    selected: list[CourseSummary] = []
    seen_ids: set[int] = set()

    for selector in selectors:
        selector_stripped = selector.strip()
        if selector_stripped in by_id:
            course = by_id[selector_stripped]
        else:
            matches = by_code.get(selector_stripped.lower(), [])
            if not matches:
                _fail(
                    f"Course selector {selector!r} did not match any course id/course_code."
                )
            if len(matches) > 1:
                ids = ", ".join(str(item.id) for item in matches)
                _fail(
                    f"Course code {selector!r} is ambiguous across ids: {ids}. "
                    "Use --course with explicit id(s)."
                )
            course = matches[0]

        if course.id not in seen_ids:
            seen_ids.add(course.id)
            selected.append(course)

    return selected


def _render_config_table(cfg: AppConfig) -> Table:
    table = Table(title="cvsctl Config")
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    table.add_row("base_url", cfg.base_url or "")
    table.add_row("default_dest", cfg.default_dest or "")
    table.add_row("effective_dest", str(_resolve_destination(None, cfg)))
    table.add_row("default_concurrency", str(cfg.default_concurrency))
    return table


def _download_for_courses(
    *,
    client: CanvasClient,
    selected_courses: list[CourseSummary],
    sources: list[str],
    dest_root: Path,
    force: bool,
    concurrency: int,
    base_url: str,
    selected_file_ids: dict[int, set[int]] | None = None,
) -> int:
    run_id = str(uuid.uuid4())
    started_at = _iso_now()

    summary_table = Table(title="Download Summary")
    summary_table.add_column("Course")
    summary_table.add_column("Downloaded", justify="right")
    summary_table.add_column("Skipped", justify="right")
    summary_table.add_column("Failed", justify="right")
    summary_table.add_column("Unresolved", justify="right")
    summary_table.add_column("Manifest")

    run_items: list[dict[str, object]] = []
    run_courses: list[dict[str, object]] = []
    had_failures = False

    for course in selected_courses:
        remote_files, warnings = collect_remote_files_for_course(client, course.id, sources)

        if selected_file_ids and course.id in selected_file_ids:
            allowed = selected_file_ids[course.id]
            remote_files = [item for item in remote_files if item.file_id in allowed]

        if not remote_files and not warnings:
            console.print(f"[yellow]No files found for course {course.id} ({course.name}).[/yellow]")

        course_slug = build_course_slug(course)
        existing_manifest = load_manifest(course_manifest_path(dest_root, course_slug))
        previous_by_file_id = index_items_by_file_id(existing_manifest)

        tasks = plan_course_download_tasks(course, remote_files, dest_root=dest_root)
        results = download_tasks(
            client,
            tasks,
            previous_items_by_file_id=previous_by_file_id,
            force=force,
            concurrency=concurrency,
            console=console,
        )

        manifest_items = [result_to_manifest_item(result) for result in results]
        manifest_items.extend(
            warning_to_manifest_item(warning, course_id=course.id) for warning in warnings
        )

        completed_at = _iso_now()
        course_payload = {
            "run_id": run_id,
            "base_url": base_url,
            "course_id": course.id,
            "sources": sources,
            "started_at": started_at,
            "completed_at": completed_at,
            "items": manifest_items,
        }
        course_manifest = write_course_manifest(dest_root, course_slug, course_payload)

        counts = summarize_results(results)
        unresolved_count = len(warnings)
        if counts["failed"] > 0:
            had_failures = True

        summary_table.add_row(
            f"{course.course_code or course.id} ({course.id})",
            str(counts["downloaded"]),
            str(counts["skipped"]),
            str(counts["failed"]),
            str(unresolved_count),
            str(course_manifest),
        )

        run_courses.append(
            {
                "course_id": course.id,
                "course_code": course.course_code,
                "course_name": course.name,
                "manifest_path": str(course_manifest),
                "counts": counts,
                "unresolved": unresolved_count,
            }
        )
        run_items.extend(manifest_items)

    console.print(summary_table)

    run_payload = {
        "run_id": run_id,
        "base_url": base_url,
        "sources": sources,
        "started_at": started_at,
        "completed_at": _iso_now(),
        "courses": run_courses,
        "items": run_items,
    }
    run_manifest = write_run_summary(dest_root, run_payload)
    console.print(f"[green]Run summary:[/green] {run_manifest}")

    return 1 if had_failures else 0


def _tasks_from_manifest_payload(payload: dict[str, object]) -> tuple[str, list[DownloadTask]]:
    base_url = payload.get("base_url")
    if not isinstance(base_url, str) or not base_url:
        _fail("Manifest does not include a valid base_url.")

    default_course_id = payload.get("course_id") if isinstance(payload.get("course_id"), int) else -1
    items = payload.get("items")
    if not isinstance(items, list):
        _fail("Manifest format invalid: expected top-level list at key 'items'.")

    tasks: list[DownloadTask] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        status = item.get("status")
        if status not in {"failed", "pending"}:
            continue

        file_id = item.get("file_id")
        remote_url = item.get("remote_url")
        local_path = item.get("local_path")
        if not isinstance(file_id, int) or not isinstance(remote_url, str) or not isinstance(local_path, str):
            continue

        course_id = item.get("course_id") if isinstance(item.get("course_id"), int) else default_course_id
        source_type = item.get("source_type") if isinstance(item.get("source_type"), str) else "resume"
        source_ref = item.get("source_ref") if isinstance(item.get("source_ref"), str) else "resume"
        display_name = item.get("display_name") if isinstance(item.get("display_name"), str) else f"file-{file_id}"
        size = item.get("size") if isinstance(item.get("size"), int) else None
        updated_at = item.get("updated_at") if isinstance(item.get("updated_at"), str) else None

        file_obj = RemoteFile(
            file_id=file_id,
            course_id=course_id,
            display_name=display_name,
            filename=display_name,
            folder_path="",
            size=size,
            updated_at=updated_at,
            download_url=remote_url,
            source_type=source_type,
            source_ref=source_ref,
        )

        path_obj = Path(local_path).expanduser()
        course_slug = path_obj.parent.name if path_obj.parent.name else f"course-{course_id}"
        tasks.append(
            DownloadTask(
                course_id=course_id,
                course_slug=course_slug,
                file=file_obj,
                local_path=path_obj,
            )
        )

    return base_url, tasks


def _dest_root_for_manifest_path(manifest_path: Path) -> Path:
    if manifest_path.name == ".canvasctl-manifest.json":
        return manifest_path.parent.parent
    if manifest_path.parent.name == ".canvasctl-runs":
        return manifest_path.parent.parent
    return manifest_path.parent


@config_app.command("set-base-url")
def config_set_base_url(url: str) -> None:
    """Persist the default Canvas base URL."""
    try:
        cfg = set_base_url(url)
    except ConfigError as exc:
        _fail(str(exc))
    console.print(f"[green]Saved base_url:[/green] {cfg.base_url}")


@config_app.command("set-download-path")
def config_set_download_path(path: Path) -> None:
    """Persist the default download destination."""
    try:
        cfg = set_default_destination(path)
    except ConfigError as exc:
        _fail(str(exc))
    console.print(f"[green]Saved default download path:[/green] {cfg.default_dest}")


@config_app.command("clear-download-path")
def config_clear_download_path() -> None:
    """Remove the persisted default download destination."""
    try:
        cfg = clear_default_destination()
    except ConfigError as exc:
        _fail(str(exc))
    effective = _resolve_destination(None, cfg)
    console.print("[green]Cleared default download path.[/green]")
    console.print(f"[green]Effective download path:[/green] {effective}")


@config_app.command("show")
def config_show() -> None:
    """Show effective local config."""
    cfg = _load_config_or_fail()
    console.print(_render_config_table(cfg))


@courses_app.command("list")
def courses_list(
    all_courses: bool = typer.Option(False, "--all", help="Include non-active courses."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON output."),
    base_url: str | None = typer.Option(None, "--base-url", help="Canvas instance URL override."),
) -> None:
    """List courses from Canvas."""
    cfg = _load_config_or_fail()
    resolved_base_url = _resolve_base_url_or_fail(cfg, base_url)

    def action(client: CanvasClient) -> int:
        courses = sort_courses(client.list_courses(include_all=all_courses))
        if json_output:
            payload = [course_to_dict(course) for course in courses]
            console.print(json.dumps(payload, indent=2))
        else:
            console.print(render_courses_table(courses))
        return 0

    _run_with_client(resolved_base_url, action)


@grades_app.command("summary")
def grades_summary(
    all_courses: bool = typer.Option(False, "--all", help="Include non-active courses."),
    detailed: bool = typer.Option(
        False, "--detailed", help="Show per-assignment grade breakdown."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON output."),
    course_selectors: list[str] | None = typer.Option(
        None,
        "--course",
        "-c",
        help="Course ID or course code. Use multiple times to filter.",
    ),
    base_url: str | None = typer.Option(
        None, "--base-url", help="Canvas instance URL override."
    ),
) -> None:
    """Show grade summary for enrolled courses."""
    cfg = _load_config_or_fail()
    resolved_base_url = _resolve_base_url_or_fail(cfg, base_url)

    def action(client: CanvasClient) -> int:
        all_grades = sort_grades(
            client.list_courses_with_grades(include_all=all_courses)
        )

        if course_selectors:
            course_summaries = [
                CourseSummary(
                    id=g.course_id,
                    course_code=g.course_code,
                    name=g.course_name,
                    workflow_state=None,
                    term_name=None,
                    start_at=None,
                    end_at=None,
                )
                for g in all_grades
            ]
            selected = _resolve_courses_from_selectors(
                course_summaries, course_selectors
            )
            selected_ids = {c.id for c in selected}
            all_grades = [g for g in all_grades if g.course_id in selected_ids]

        if not detailed:
            if json_output:
                payload = [grade_to_dict(g) for g in all_grades]
                console.print(json.dumps(payload, indent=2))
            else:
                console.print(render_grades_summary_table(all_grades))
        else:
            if json_output:
                payload = []
                for course_grade in all_grades:
                    assignments = sort_assignment_grades(
                        client.list_assignment_grades(course_grade.course_id)
                    )
                    payload.append(
                        {
                            "course": grade_to_dict(course_grade),
                            "assignments": [
                                assignment_grade_to_dict(a) for a in assignments
                            ],
                        }
                    )
                console.print(json.dumps(payload, indent=2))
            else:
                for course_grade in all_grades:
                    assignments = sort_assignment_grades(
                        client.list_assignment_grades(course_grade.course_id)
                    )
                    console.print(
                        render_detailed_grades_table(course_grade, assignments)
                    )
                    console.print()

        return 0

    _run_with_client(resolved_base_url, action)


@download_app.command("run")
def download_run(
    course_selectors: list[str] = typer.Option(
        ...,
        "--course",
        "-c",
        help="Course ID or course code. Use multiple times for multiple courses.",
    ),
    source_values: list[SourceChoice] | None = typer.Option(
        None,
        "--source",
        "-s",
        help=f"Source type(s): {', '.join(ALL_SOURCES)}. Defaults to all.",
    ),
    dest: Path | None = typer.Option(None, "--dest", help="Destination root directory."),
    export_dest: bool = typer.Option(
        False,
        "--export-dest",
        help="Persist --dest as the default download path for future commands.",
    ),
    overwrite: str | None = typer.Option(
        None,
        "--overwrite",
        help="Overwrite existing files (true/false). Default: false.",
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
    concurrency: int | None = typer.Option(
        None,
        "--concurrency",
        help="Parallel download workers. Defaults to configured value (12).",
    ),
    base_url: str | None = typer.Option(None, "--base-url", help="Canvas instance URL override."),
) -> None:
    """Download files for selected courses."""
    cfg = _load_config_or_fail()
    resolved_base_url = _resolve_base_url_or_fail(cfg, base_url)
    destination = _resolve_destination(dest, cfg)
    _persist_destination_if_requested(
        export_dest=export_dest,
        provided_dest=dest,
        resolved_dest=destination,
    )
    resolved_concurrency = _resolve_concurrency(concurrency, cfg)
    resolved_overwrite = _resolve_overwrite(overwrite, force)

    try:
        selected_sources = normalize_sources([item.value for item in (source_values or [])])
    except ValueError as exc:
        _fail(str(exc))

    def action(client: CanvasClient) -> int:
        all_courses = sort_courses(client.list_courses(include_all=True))
        selected_courses = _resolve_courses_from_selectors(all_courses, course_selectors)
        return _download_for_courses(
            client=client,
            selected_courses=selected_courses,
            sources=selected_sources,
            dest_root=destination,
            force=resolved_overwrite,
            concurrency=resolved_concurrency,
            base_url=resolved_base_url,
        )

    exit_code = _run_with_client(resolved_base_url, action)
    if exit_code:
        raise typer.Exit(code=exit_code)


@download_app.command("interactive")
def download_interactive(
    dest: Path | None = typer.Option(None, "--dest", help="Destination root directory."),
    export_dest: bool = typer.Option(
        False,
        "--export-dest",
        help="Persist --dest as the default download path for future commands.",
    ),
    base_url: str | None = typer.Option(None, "--base-url", help="Canvas instance URL override."),
    concurrency: int | None = typer.Option(
        None,
        "--concurrency",
        help="Parallel download workers. Defaults to configured value (12).",
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
) -> None:
    """Run guided prompts to select courses/files to download."""
    cfg = _load_config_or_fail()
    resolved_base_url = _resolve_base_url_or_fail(cfg, base_url)
    destination = _resolve_destination(dest, cfg)
    _persist_destination_if_requested(
        export_dest=export_dest,
        provided_dest=dest,
        resolved_dest=destination,
    )
    resolved_concurrency = _resolve_concurrency(concurrency, cfg)

    def action(client: CanvasClient) -> int:
        all_courses = sort_courses(client.list_courses(include_all=False))
        if not all_courses:
            console.print("[yellow]No active courses available.[/yellow]")
            return 0

        try:
            selection = prompt_interactive_selection(all_courses)
        except RuntimeError as exc:
            _fail(str(exc))
        selected_map = {course.id: course for course in all_courses}
        selected_courses = [
            selected_map[course_id]
            for course_id in selection.course_ids
            if course_id in selected_map
        ]
        if not selected_courses:
            _fail("No valid courses selected.")

        file_selection: dict[int, set[int]] = {}
        if selection.granularity == "file":
            for course in selected_courses:
                remote_files, _warnings = collect_remote_files_for_course(
                    client,
                    course.id,
                    selection.sources,
                )
                selected_file_ids = prompt_file_selection(course=course, remote_files=remote_files)
                file_selection[course.id] = selected_file_ids

        return _download_for_courses(
            client=client,
            selected_courses=selected_courses,
            sources=selection.sources,
            dest_root=destination,
            force=force,
            concurrency=resolved_concurrency,
            base_url=resolved_base_url,
            selected_file_ids=file_selection if file_selection else None,
        )

    exit_code = _run_with_client(resolved_base_url, action)
    if exit_code:
        raise typer.Exit(code=exit_code)


@download_app.command("resume")
def download_resume(
    manifest: Path = typer.Option(
        ...,
        "--manifest",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to a prior run summary or course manifest JSON.",
    ),
) -> None:
    """Resume failed/pending downloads from a manifest file."""
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _fail(f"Could not parse manifest JSON: {exc}")

    if not isinstance(payload, dict):
        _fail("Manifest must be a JSON object.")

    base_url, tasks = _tasks_from_manifest_payload(payload)
    if not tasks:
        console.print("[yellow]No failed/pending items found in manifest.[/yellow]")
        return

    destination_root = _dest_root_for_manifest_path(manifest)

    def action(client: CanvasClient) -> int:
        results = download_tasks(
            client,
            tasks,
            previous_items_by_file_id={},
            force=True,
            concurrency=DEFAULT_CONCURRENCY,
            console=console,
        )

        counts = summarize_results(results)
        summary_table = Table(title="Resume Summary")
        summary_table.add_column("Downloaded", justify="right")
        summary_table.add_column("Skipped", justify="right")
        summary_table.add_column("Failed", justify="right")
        summary_table.add_row(
            str(counts["downloaded"]),
            str(counts["skipped"]),
            str(counts["failed"]),
        )
        console.print(summary_table)

        run_payload = {
            "run_id": str(uuid.uuid4()),
            "base_url": base_url,
            "sources": ["resume"],
            "started_at": _iso_now(),
            "completed_at": _iso_now(),
            "courses": [],
            "items": [result_to_manifest_item(result) for result in results],
        }
        run_summary = write_run_summary(destination_root, run_payload)
        console.print(f"[green]Resume summary:[/green] {run_summary}")

        return 1 if counts["failed"] else 0

    exit_code = _run_with_client(base_url, action)
    if exit_code:
        raise typer.Exit(code=exit_code)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
