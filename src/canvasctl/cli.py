from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Sequence

import typer
from rich.console import Console
from rich.table import Table

from canvasctl.auth import AuthError, TokenInfo, prompt_for_token, resolve_token
from canvasctl.canvas_api import (
    CanvasApiError,
    CanvasClient,
    CanvasUnauthorizedError,
    CourseSummary,
)
from canvasctl.config import (
    AppConfig,
    ConfigError,
    DEFAULT_CONCURRENCY,
    clear_course_path,
    clear_default_destination,
    get_course_path,
    load_config,
    resolve_base_url,
    set_base_url,
    set_course_path,
    set_default_destination,
)
from canvasctl.courses import course_to_dict, render_courses_table, sort_courses
from canvasctl.grades import (
    _default_export_dir,
    assignment_grade_to_dict,
    export_grades_csv,
    export_grades_json,
    grade_to_dict,
    render_detailed_grades_table,
    render_grades_summary_table,
    sort_assignment_grades,
    sort_grades,
)
from canvasctl.downloader import (
    build_course_slug,
    download_tasks,
    plan_course_download_tasks,
    result_to_manifest_item,
    summarize_results,
)
from canvasctl.interactive import prompt_interactive_selection
from canvasctl.manifest import (
    course_manifest_path,
    index_items_by_file_id,
    load_manifest,
    write_course_manifest,
    write_manifest,
)
from canvasctl.sources import (
    ALL_SOURCES,
    normalize_sources,
    warning_to_manifest_item,
    collect_remote_files_for_course,
)
from canvasctl.course_cache import cache_info, courses_from_cache, load_cache, write_cache

app = typer.Typer(help="Canvas LMS CLI")
config_app = typer.Typer(help="Manage local cvsctl config")
courses_app = typer.Typer(help="List and inspect courses")
download_app = typer.Typer(help="Download course files")
grades_app = typer.Typer(help="View course grades")
assignments_app = typer.Typer(help="Submit assignments")
cache_app = typer.Typer(help="Manage the local course list cache")

mcp_app = typer.Typer(help="MCP server commands")

app.add_typer(config_app, name="config")
app.add_typer(courses_app, name="courses")
app.add_typer(download_app, name="download")
app.add_typer(grades_app, name="grades")
app.add_typer(assignments_app, name="assignments")
app.add_typer(cache_app, name="cache")
app.add_typer(mcp_app, name="mcp")

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


def _resolve_assignment_from_selector(
    assignments: list[dict[str, Any]],
    selector: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    stripped = selector.strip()
    if stripped.isdigit():
        assignment_id = int(stripped)
        for assignment in assignments:
            if assignment.get("id") == assignment_id:
                return assignment, []
        return None, []

    normalized = stripped.casefold()
    exact = [
        assignment
        for assignment in assignments
        if str(assignment.get("name") or "").strip().casefold() == normalized
    ]
    if len(exact) == 1:
        return exact[0], []
    if len(exact) > 1:
        return None, exact

    partial = [
        assignment
        for assignment in assignments
        if normalized in str(assignment.get("name") or "").strip().casefold()
    ]
    if len(partial) == 1:
        return partial[0], []
    if len(partial) > 1:
        return None, partial
    return None, []


def _render_config_table(cfg: AppConfig) -> Table:
    table = Table(title="cvsctl Config")
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    table.add_row("base_url", cfg.base_url or "")
    table.add_row("default_dest", cfg.default_dest or "")
    table.add_row("effective_dest", str(_resolve_destination(None, cfg)))
    table.add_row("default_concurrency", str(cfg.default_concurrency))
    course_path_count = len(cfg.course_paths) if cfg.course_paths else 0
    table.add_row("course_paths", str(course_path_count))
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
    course_paths: dict[str, str] | None = None,
) -> int:
    started_at = _iso_now()

    summary_table = Table(title="Download Summary")
    summary_table.add_column("Course")
    summary_table.add_column("Downloaded", justify="right")
    summary_table.add_column("Skipped", justify="right")
    summary_table.add_column("Failed", justify="right")
    summary_table.add_column("Unresolved", justify="right")

    had_failures = False

    for course in selected_courses:
        remote_files, warnings = collect_remote_files_for_course(client, course.id, sources)

        if not remote_files and not warnings:
            console.print(f"[yellow]No files found for course {course.id} ({course.name}).[/yellow]")

        course_slug = build_course_slug(course)
        custom_dest: Path | None = None
        if course_paths and str(course.id) in course_paths:
            custom_dest = Path(course_paths[str(course.id)])

        if custom_dest is not None:
            manifest_file = custom_dest / ".canvasctl-manifest.json"
        else:
            manifest_file = course_manifest_path(dest_root, course_slug)

        existing_manifest = load_manifest(manifest_file)
        previous_by_file_id = index_items_by_file_id(existing_manifest)

        tasks = plan_course_download_tasks(
            course, remote_files, dest_root=dest_root, course_dest=custom_dest,
        )
        results = download_tasks(
            client,
            tasks,
            previous_items_by_file_id=previous_by_file_id,
            force=force,
            concurrency=concurrency,
            console=console,
        )

        manifest_items = []
        for result in results:
            if result.status == "skipped":
                prev = previous_by_file_id.get(result.task.file.file_id)
                if prev is not None:
                    manifest_items.append(prev)
                    continue
            manifest_items.append(result_to_manifest_item(result))
        manifest_items.extend(
            warning_to_manifest_item(warning, course_id=course.id) for warning in warnings
        )

        completed_at = _iso_now()
        course_payload = {
            "base_url": base_url,
            "course_id": course.id,
            "sources": sources,
            "started_at": started_at,
            "completed_at": completed_at,
            "items": manifest_items,
        }

        if custom_dest is not None:
            write_manifest(manifest_file, course_payload)
        else:
            write_course_manifest(dest_root, course_slug, course_payload)

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
        )

    console.print(summary_table)

    return 1 if had_failures else 0


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


@config_app.command("set-course-path")
def config_set_course_path(
    course_id: int = typer.Argument(..., help="Canvas course ID."),
    path: Path = typer.Argument(..., help="Local directory for this course's downloads."),
) -> None:
    """Map a course to a specific download directory."""
    try:
        cfg = set_course_path(course_id, path)
    except ConfigError as exc:
        _fail(str(exc))
    resolved = cfg.course_paths[str(course_id)] if cfg.course_paths else str(path)
    console.print(f"[green]Saved course path for {course_id}:[/green] {resolved}")


@config_app.command("clear-course-path")
def config_clear_course_path(
    course_id: int = typer.Argument(..., help="Canvas course ID."),
) -> None:
    """Remove a per-course download path mapping."""
    try:
        clear_course_path(course_id)
    except ConfigError as exc:
        _fail(str(exc))
    console.print(f"[green]Cleared course path for {course_id}.[/green]")


@config_app.command("show-course-paths")
def config_show_course_paths() -> None:
    """Show all per-course download path mappings."""
    cfg = _load_config_or_fail()
    if not cfg.course_paths:
        console.print("No course paths configured.")
        return
    table = Table(title="Course Download Paths")
    table.add_column("Course ID", style="cyan")
    table.add_column("Path")
    for cid, cpath in sorted(cfg.course_paths.items()):
        table.add_row(cid, cpath)
    console.print(table)


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
        # Opportunistic cache write for active courses
        if not all_courses:
            try:
                write_cache(resolved_base_url, courses)
            except Exception:
                pass  # Cache write failure is non-fatal
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


class ExportFormat(str, Enum):
    csv = "csv"
    json = "json"


@grades_app.command("export")
def grades_export(
    all_courses: bool = typer.Option(False, "--all", help="Include non-active courses."),
    detailed: bool = typer.Option(
        False, "--detailed", help="Include per-assignment breakdown."
    ),
    fmt: ExportFormat = typer.Option(
        ExportFormat.csv,
        "--format",
        "-f",
        help="Export format: csv (default) or json.",
    ),
    dest: Path | None = typer.Option(
        None,
        "--dest",
        help="Destination directory for the export file. Defaults to ~/Downloads.",
    ),
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
    """Export grades to a CSV or JSON file."""
    cfg = _load_config_or_fail()
    resolved_base_url = _resolve_base_url_or_fail(cfg, base_url)
    export_dir = dest.expanduser().resolve() if dest is not None else _default_export_dir()

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

        assignments_by_course: dict[int, list] | None = None
        if detailed:
            assignments_by_course = {}
            for course_grade in all_grades:
                assignments_by_course[course_grade.course_id] = sort_assignment_grades(
                    client.list_assignment_grades(course_grade.course_id)
                )

        extension = fmt.value
        filename = f"canvasctl-grades.{extension}"
        file_path = export_dir / filename

        if fmt == ExportFormat.json:
            written = export_grades_json(all_grades, assignments_by_course, file_path)
        else:
            written = export_grades_csv(all_grades, assignments_by_course, file_path)

        console.print(f"[green]Exported grades to:[/green] {written}")
        return 0

    _run_with_client(resolved_base_url, action)


@assignments_app.command("submit")
def assignments_submit(
    course_selector: str = typer.Option(
        ...,
        "--course",
        "-c",
        help="Course ID or course code.",
    ),
    assignment_selector: str = typer.Option(
        ...,
        "--assignment",
        "-a",
        help="Assignment ID or assignment name.",
    ),
    file_paths: list[Path] | None = typer.Option(
        None,
        "--file",
        help="Absolute or relative path to local file. Repeat for multiple files.",
    ),
    text_submission: str | None = typer.Option(
        None,
        "--text",
        help="Submission body for online_text_entry assignments.",
    ),
    url_submission: str | None = typer.Option(
        None,
        "--url",
        help="Submission URL for online_url assignments.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON output."),
    base_url: str | None = typer.Option(
        None, "--base-url", help="Canvas instance URL override."
    ),
) -> None:
    """Submit a Canvas assignment."""
    cfg = _load_config_or_fail()
    resolved_base_url = _resolve_base_url_or_fail(cfg, base_url)

    def action(client: CanvasClient) -> int:
        courses = sort_courses(client.list_courses(include_all=True))
        selected_courses = _resolve_courses_from_selectors(courses, [course_selector])
        if len(selected_courses) != 1:
            _fail(f"Expected exactly one course for selector {course_selector!r}.")
        course = selected_courses[0]

        assignments = client.list_assignments(course.id)
        assignment, ambiguous = _resolve_assignment_from_selector(
            assignments, assignment_selector
        )
        if ambiguous:
            table = Table(title="Ambiguous assignment selector")
            table.add_column("Assignment ID", style="cyan")
            table.add_column("Assignment Name")
            table.add_column("Due At")
            table.add_column("URL")
            for item in ambiguous:
                table.add_row(
                    str(item.get("id") or ""),
                    str(item.get("name") or ""),
                    str(item.get("due_at") or ""),
                    str(item.get("html_url") or ""),
                )
            console.print(table)
            _fail(
                "Assignment selector matched multiple assignments. "
                "Re-run with --assignment <id>."
            )
        if assignment is None:
            _fail(f"Assignment selector {assignment_selector!r} did not match this course.")

        submission_inputs = sum(
            1 for value in (file_paths, text_submission, url_submission) if value
        )
        if submission_inputs == 0:
            _fail("One submission input is required: --file, --text, or --url.")
        if submission_inputs > 1:
            _fail("Provide only one submission input type at a time.")

        assignment_id = int(assignment["id"])
        assignment_name = str(assignment.get("name") or "")
        assignment_url = str(assignment.get("html_url") or "")
        submission_types = [
            str(item) for item in (assignment.get("submission_types") or [])
        ]

        if file_paths:
            if "online_upload" not in submission_types:
                if assignment_url:
                    console.print(f"[yellow]Manual submission URL:[/yellow] {assignment_url}")
                _fail(
                    "This assignment does not accept file uploads. "
                    f"Canvas submission_types: {submission_types}"
                )

            resolved_files: list[Path] = []
            for raw_path in file_paths:
                resolved = raw_path.expanduser().resolve()
                if not resolved.is_file():
                    _fail(f"File path does not exist or is not a file: {raw_path}")
                resolved_files.append(resolved)

            file_ids: list[int] = []
            for local_path in resolved_files:
                init_payload = client.init_assignment_file_upload(
                    course.id,
                    assignment_id,
                    filename=local_path.name,
                    size=local_path.stat().st_size,
                )
                upload_url = init_payload.get("upload_url")
                upload_params = init_payload.get("upload_params") or {}
                if not isinstance(upload_url, str) or not upload_url:
                    _fail(f"Canvas did not provide upload_url for {local_path.name}.")
                uploaded = client.upload_file_to_canvas(upload_url, upload_params, local_path)
                uploaded_id = uploaded.get("id")
                if not isinstance(uploaded_id, int):
                    _fail(f"Canvas upload did not return a file id for {local_path.name}.")
                file_ids.append(uploaded_id)

            submission = client.submit_assignment(
                course.id,
                assignment_id,
                submission_type="online_upload",
                body={"file_ids": file_ids},
            )
            action_name = "submitted_online_upload"
        elif text_submission:
            if "online_text_entry" not in submission_types:
                if assignment_url:
                    console.print(f"[yellow]Manual submission URL:[/yellow] {assignment_url}")
                _fail(
                    "This assignment does not accept text entry submissions. "
                    f"Canvas submission_types: {submission_types}"
                )
            submission = client.submit_assignment(
                course.id,
                assignment_id,
                submission_type="online_text_entry",
                body={"body": text_submission},
            )
            action_name = "submitted_online_text_entry"
        else:
            assert url_submission is not None
            if "online_url" not in submission_types:
                if assignment_url:
                    console.print(f"[yellow]Manual submission URL:[/yellow] {assignment_url}")
                _fail(
                    "This assignment does not accept URL submissions. "
                    f"Canvas submission_types: {submission_types}"
                )
            submission = client.submit_assignment(
                course.id,
                assignment_id,
                submission_type="online_url",
                body={"url": url_submission},
            )
            action_name = "submitted_online_url"

        payload = {
            "status": "completed",
            "action_taken": action_name,
            "course_id": course.id,
            "course_name": course.name,
            "assignment_id": assignment_id,
            "assignment_name": assignment_name,
            "url": assignment_url,
            "submission": submission,
        }
        if json_output:
            console.print(json.dumps(payload, indent=2))
        else:
            table = Table(title="Assignment Submission")
            table.add_column("Field", style="cyan")
            table.add_column("Value")
            table.add_row("status", payload["status"])
            table.add_row("action_taken", payload["action_taken"])
            table.add_row("course_id", str(course.id))
            table.add_row("assignment_id", str(assignment_id))
            table.add_row("assignment_name", assignment_name)
            if assignment_url:
                table.add_row("url", assignment_url)
            console.print(table)
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
            course_paths=cfg.course_paths,
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

        return _download_for_courses(
            client=client,
            selected_courses=selected_courses,
            sources=selection.sources,
            dest_root=destination,
            force=force,
            concurrency=resolved_concurrency,
            base_url=resolved_base_url,
            course_paths=cfg.course_paths,
        )

    exit_code = _run_with_client(resolved_base_url, action)
    if exit_code:
        raise typer.Exit(code=exit_code)


@cache_app.command("refresh")
def cache_refresh(
    base_url: str | None = typer.Option(None, "--base-url", help="Canvas instance URL override."),
) -> None:
    """Fetch current courses from Canvas and update the local cache."""
    cfg = _load_config_or_fail()
    resolved_base_url = _resolve_base_url_or_fail(cfg, base_url)

    def action(client: CanvasClient) -> int:
        courses = sort_courses(client.list_courses(include_all=False))
        path = write_cache(resolved_base_url, courses)
        console.print(f"[green]Cached {len(courses)} course(s) to:[/green] {path}")
        console.print(render_courses_table(courses))
        return 0

    _run_with_client(resolved_base_url, action)


@cache_app.command("show")
def cache_show(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON output."),
    base_url: str | None = typer.Option(None, "--base-url", help="Canvas instance URL override."),
) -> None:
    """Show the contents of the local course list cache."""
    cfg = _load_config_or_fail()
    resolved_base_url = _resolve_base_url_or_fail(cfg, base_url)
    info = cache_info(resolved_base_url)

    if not info["present"]:
        console.print("[yellow]No course cache found.[/yellow]")
        console.print("Run [bold]cvsctl cache refresh[/bold] to populate it.")
        return

    if json_output:
        cached = load_cache(resolved_base_url)
        console.print(json.dumps(cached, indent=2))
        return

    # Table view
    table = Table(title="Course Cache Info")
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    table.add_row("path", info["path"])
    table.add_row("base_url", info["base_url"] or "")
    table.add_row("fetched_at", info["fetched_at"] or "")
    ttl_display = str(info["ttl_seconds"]) + "s" if info["ttl_seconds"] else "never expires"
    table.add_row("ttl", ttl_display)
    table.add_row("courses", str(info["course_count"]))
    table.add_row("valid", str(info["valid"]))
    console.print(table)

    # Also render the course list
    cached = load_cache(resolved_base_url)
    cached_courses = courses_from_cache(cached)
    if cached_courses:
        console.print(render_courses_table(cached_courses))


@mcp_app.command("serve")
def mcp_serve() -> None:
    """Start the Canvas MCP server (STDIO transport)."""
    from canvasctl.mcp_server import main as mcp_main

    mcp_main()


@app.command("onboard")
def onboard_cmd() -> None:
    """Interactive setup wizard for new users."""
    from canvasctl.onboard import run_onboard

    try:
        run_onboard(console)
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Setup cancelled.[/yellow]")
        raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
