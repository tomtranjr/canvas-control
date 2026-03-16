"""Canvas MCP server — exposes Canvas LMS data via Model Context Protocol."""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import Context, FastMCP
from rich.console import Console

from canvasctl.canvas_api import CanvasClient, CourseSummary
from canvasctl.config import (
    AppConfig,
    ConfigError,
    get_course_path,
    load_config,
    set_course_path,
    set_default_destination,
)
from canvasctl.downloader import (
    build_course_slug,
    download_tasks,
    plan_course_download_tasks,
    result_to_manifest_item,
    summarize_results,
)
from canvasctl.manifest import (
    course_manifest_path,
    index_items_by_file_id,
    load_manifest,
    write_course_manifest,
    write_manifest,
)
from canvasctl.sources import (
    collect_remote_files_for_course,
    normalize_sources,
    warning_to_manifest_item,
)

logger = logging.getLogger(__name__)


def _safe_error(exc: Exception) -> str:
    """Return a user-safe error string, logging the full exception."""
    if isinstance(exc, (RuntimeError, ValueError)):
        return str(exc)
    logger.exception("Unexpected error in MCP tool")
    return "An internal error occurred. Check server logs for details."


@dataclass
class AppContext:
    client: CanvasClient
    base_url: str
    config: AppConfig
    timezone: ZoneInfo | None = None


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    token = os.environ.get("CANVAS_TOKEN", "")
    if not token:
        raise RuntimeError(
            "CANVAS_TOKEN environment variable is required. "
            "Set it to your Canvas API access token."
        )

    try:
        cfg = load_config()
    except (ConfigError, FileNotFoundError, OSError):
        cfg = AppConfig()

    base_url = os.environ.get("CANVAS_BASE_URL", "") or (cfg.base_url or "")
    if not base_url:
        raise RuntimeError(
            "CANVAS_BASE_URL environment variable or config base_url is required. "
            "Set it to your Canvas instance URL (e.g. https://school.instructure.com)."
        )

    tz: ZoneInfo | None = None
    tz_name = os.environ.get("CANVAS_TIMEZONE", "")
    if tz_name:
        tz = ZoneInfo(tz_name)

    client = CanvasClient(base_url, token)
    try:
        yield AppContext(client=client, base_url=base_url, config=cfg, timezone=tz)
    finally:
        client.close()


mcp = FastMCP("Canvas LMS", lifespan=app_lifespan)


def _get_ctx(ctx: Context) -> AppContext:
    return ctx.request_context.lifespan_context


def _json(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str)


def _strip_html(html: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def _convert_tz(iso_str: str | None, tz: ZoneInfo) -> str | None:
    """Convert an ISO 8601 UTC timestamp to the target timezone."""
    if iso_str is None:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone(tz).isoformat()
    except (ValueError, TypeError):
        return iso_str


def _localize_dates(
    obj: dict[str, Any], tz: ZoneInfo, keys: tuple[str, ...]
) -> dict[str, Any]:
    """Convert specified date keys in a dict to the target timezone."""
    for key in keys:
        if key in obj:
            obj[key] = _convert_tz(obj[key], tz)
    return obj


def _get_active_course_ids(client: CanvasClient) -> list[int]:
    courses = client.list_courses(include_all=False)
    return [c.id for c in courses]


_AUTOMATED_SUBMISSION_TYPES = {"online_upload", "online_text_entry", "online_url"}


def _normalize_assignment_name(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _assignment_search_space(client: CanvasClient, course_ids: list[int]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cid in course_ids:
        for assignment in client.list_assignments(cid):
            out.append(
                {
                    "course_id": cid,
                    "assignment": assignment,
                }
            )
    return out


def _select_assignment(
    records: list[dict[str, Any]],
    *,
    assignment_id: int | None,
    assignment_name: str | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
    if assignment_id is not None:
        matches = [item for item in records if int(item["assignment"].get("id", -1)) == assignment_id]
    elif assignment_name:
        needle = _normalize_assignment_name(assignment_name)
        exact = [
            item
            for item in records
            if _normalize_assignment_name(str(item["assignment"].get("name") or "")) == needle
        ]
        if exact:
            matches = exact
        else:
            matches = [
                item
                for item in records
                if needle in _normalize_assignment_name(str(item["assignment"].get("name") or ""))
            ]
    else:
        return None, [], "Either assignment_id or assignment_name is required."

    if not matches:
        return None, [], "No matching assignment found."
    if len(matches) > 1:
        candidates: list[dict[str, Any]] = []
        for match in matches:
            assignment = match["assignment"]
            candidates.append(
                {
                    "course_id": match["course_id"],
                    "assignment_id": assignment.get("id"),
                    "assignment_name": assignment.get("name"),
                    "due_at": assignment.get("due_at"),
                    "url": assignment.get("html_url"),
                }
            )
        return None, candidates, "Assignment reference is ambiguous."
    return matches[0], [], None


def _build_complete_assignment_response(
    *,
    status: str,
    action_taken: str,
    course_id: int | None,
    assignment_id: int | None,
    assignment_name: str | None,
    url: str | None,
    next_step: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "status": status,
        "action_taken": action_taken,
        "course_id": course_id,
        "assignment_id": assignment_id,
        "assignment_name": assignment_name,
        "url": url,
        "next_step": next_step,
    }
    if extra:
        payload.update(extra)
    return payload


def _resolve_module_item_for_assignment(
    client: CanvasClient,
    *,
    course_id: int,
    assignment_id: int,
) -> tuple[int, int] | None:
    modules = client.list_modules(course_id)
    for module in modules:
        module_id = module.get("id")
        items = module.get("items") or []
        if module_id is None or not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            content_id = item.get("content_id")
            item_type = str(item.get("type") or "")
            item_id = item.get("id")
            if content_id == assignment_id and item_id is not None and item_type.lower() == "assignment":
                return int(module_id), int(item_id)
    return None


def _validate_absolute_file_paths(raw_paths: list[str]) -> tuple[list[Path], str | None]:
    files: list[Path] = []
    for raw in raw_paths:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            return [], f"File path must be absolute: {raw}"
        if not path.is_file():
            return [], f"File path does not exist or is not a file: {raw}"
        files.append(path)
    return files, None


@mcp.tool()
def list_courses(ctx: Context, include_all: bool = False) -> str:
    """List Canvas courses. By default shows only active enrollments.

    Args:
        include_all: If True, include concluded/past courses too.
    """
    try:
        app = _get_ctx(ctx)
        courses = app.client.list_courses(include_all=include_all)
        items = [asdict(c) for c in courses]
        if app.timezone:
            for item in items:
                _localize_dates(item, app.timezone, ("start_at", "end_at"))
        return _json(items)
    except Exception as exc:
        return _json({"error": _safe_error(exc)})


@mcp.tool()
def get_upcoming_assignments(
    ctx: Context,
    course_id: int | None = None,
    days_ahead: int = 14,
) -> str:
    """Get upcoming assignments that are due within a time window.

    Args:
        course_id: Optional course ID to filter. If omitted, checks all active courses.
        days_ahead: Number of days ahead to look for due dates (default 14).
    """
    try:
        app = _get_ctx(ctx)
        now = datetime.now(UTC)
        cutoff = now + timedelta(days=days_ahead)

        course_ids = [course_id] if course_id else _get_active_course_ids(app.client)
        results: list[dict[str, Any]] = []

        for cid in course_ids:
            assignments = app.client.list_upcoming_assignments(cid)
            for a in assignments:
                if a.due_at is None:
                    continue
                try:
                    due = datetime.fromisoformat(a.due_at.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if due > now and due <= cutoff:
                    d = asdict(a)
                    if app.timezone:
                        _localize_dates(d, app.timezone, ("due_at", "lock_at", "unlock_at"))
                    results.append(d)

        results.sort(key=lambda x: x.get("due_at") or "")
        return _json(results)
    except Exception as exc:
        return _json({"error": _safe_error(exc)})


@mcp.tool()
def get_announcements(
    ctx: Context,
    course_id: int | None = None,
    limit: int = 10,
) -> str:
    """Get recent announcements from Canvas courses.

    Args:
        course_id: Optional course ID to filter. If omitted, gets from all active courses.
        limit: Maximum number of announcements to return (default 10).
    """
    try:
        app = _get_ctx(ctx)
        course_ids = [course_id] if course_id else _get_active_course_ids(app.client)
        if not course_ids:
            return _json([])

        announcements = app.client.list_announcements(course_ids)
        items = [asdict(a) for a in announcements[:limit]]
        if app.timezone:
            for item in items:
                _localize_dates(item, app.timezone, ("posted_at",))
        return _json(items)
    except Exception as exc:
        return _json({"error": _safe_error(exc)})


@mcp.tool()
def get_calendar_events(
    ctx: Context,
    course_id: int | None = None,
    days_ahead: int = 14,
) -> str:
    """Get calendar events within a time window.

    Args:
        course_id: Optional course ID to filter. If omitted, gets events from all contexts.
        days_ahead: Number of days ahead to look (default 14).
    """
    try:
        app = _get_ctx(ctx)
        now = datetime.now(UTC)
        end = now + timedelta(days=days_ahead)
        start_date = now.strftime("%Y-%m-%d")
        end_date = end.strftime("%Y-%m-%d")

        context_codes: list[str] | None = None
        if course_id:
            context_codes = [f"course_{course_id}"]

        events = app.client.list_calendar_events(
            start_date=start_date,
            end_date=end_date,
            context_codes=context_codes,
        )
        items = [asdict(e) for e in events]
        if app.timezone:
            for item in items:
                _localize_dates(item, app.timezone, ("start_at", "end_at"))
        return _json(items)
    except Exception as exc:
        return _json({"error": _safe_error(exc)})


@mcp.tool()
def get_syllabus(ctx: Context, course_id: int) -> str:
    """Get the syllabus for a specific course.

    Args:
        course_id: The Canvas course ID.
    """
    try:
        app = _get_ctx(ctx)
        data = app.client.get_course_syllabus(course_id)
        syllabus_html = data.get("syllabus_body") or ""
        result = {
            "course_id": data.get("id"),
            "course_name": data.get("name"),
            "syllabus_body": syllabus_html,
            "syllabus_body_text": _strip_html(syllabus_html) if syllabus_html else "",
        }
        return _json(result)
    except Exception as exc:
        return _json({"error": _safe_error(exc)})


@mcp.tool()
def get_grades_summary(ctx: Context, course_id: int | None = None) -> str:
    """Get grade summary for enrolled courses.

    Args:
        course_id: Optional course ID to filter. If omitted, shows all active courses.
    """
    try:
        app = _get_ctx(ctx)
        grades = app.client.list_courses_with_grades(include_all=False)
        if course_id:
            grades = [g for g in grades if g.course_id == course_id]
        return _json([asdict(g) for g in grades])
    except Exception as exc:
        return _json({"error": _safe_error(exc)})


@mcp.tool()
def get_grades_detailed(ctx: Context, course_id: int) -> str:
    """Get detailed per-assignment grades for a specific course.

    Args:
        course_id: The Canvas course ID.
    """
    try:
        app = _get_ctx(ctx)
        grades = app.client.list_assignment_grades(course_id)
        items = [asdict(g) for g in grades]
        if app.timezone:
            for item in items:
                _localize_dates(item, app.timezone, ("submitted_at",))
        return _json(items)
    except Exception as exc:
        return _json({"error": _safe_error(exc)})


@mcp.tool()
def list_course_files(ctx: Context, course_id: int) -> str:
    """List all files in a Canvas course.

    Args:
        course_id: The Canvas course ID.
    """
    try:
        app = _get_ctx(ctx)
        files = app.client.list_course_files(course_id)
        return _json(files)
    except Exception as exc:
        return _json({"error": _safe_error(exc)})


@mcp.tool()
def download_file(
    ctx: Context,
    file_id: int,
    destination: str | None = None,
) -> str:
    """Download a single file from Canvas by file ID.

    Args:
        file_id: The Canvas file ID.
        destination: Optional local path. Defaults to ~/Downloads/<filename>.
    """
    try:
        app = _get_ctx(ctx)
        file_info = app.client.get_file(file_id)
        filename = file_info.get("display_name") or file_info.get("filename") or f"file-{file_id}"
        download_url = file_info.get("url") or ""
        if not download_url:
            return _json({"error": f"No download URL for file {file_id}"})

        if destination:
            dest_path = Path(destination).expanduser()
        else:
            dest_path = Path.home() / "Downloads" / filename

        bytes_written, sha256, etag = app.client.download_file(download_url, dest_path)
        return _json({
            "file_id": file_id,
            "filename": filename,
            "destination": str(dest_path),
            "bytes_written": bytes_written,
            "sha256": sha256,
        })
    except Exception as exc:
        return _json({"error": _safe_error(exc)})


@mcp.tool()
def search_course_files(
    ctx: Context,
    course_id: int,
    query: str | None = None,
    file_type: str | None = None,
    folder: str | None = None,
) -> str:
    """Search for files in a Canvas course by name, extension, or folder.

    Use this as a preview step before downloading — show the user what
    would be downloaded and let them confirm.

    Args:
        course_id: The Canvas course ID.
        query: Case-insensitive substring to match in file display name or filename.
        file_type: File extension to filter by (e.g. "pdf", "docx"). Leading dot is stripped.
        folder: Case-insensitive substring to match in the Canvas folder path.
    """
    try:
        app = _get_ctx(ctx)
        files = app.client.list_course_files(course_id)
        folder_map = app.client.list_course_folders(course_id)

        norm_query = query.casefold() if query else None
        norm_type = file_type.lstrip(".").casefold() if file_type else None
        norm_folder = folder.casefold() if folder else None

        results: list[dict[str, Any]] = []
        for f in files:
            display_name = str(f.get("display_name") or "")
            filename = str(f.get("filename") or "")
            folder_id = f.get("folder_id")
            folder_path = folder_map.get(int(folder_id), "") if folder_id is not None else ""

            if norm_query and norm_query not in display_name.casefold() and norm_query not in filename.casefold():
                continue

            if norm_type:
                ext = Path(filename).suffix.lstrip(".").casefold()
                if ext != norm_type:
                    continue

            if norm_folder and norm_folder not in folder_path.casefold():
                continue

            results.append({
                "file_id": f.get("id"),
                "display_name": display_name,
                "filename": filename,
                "folder_path": folder_path,
                "size": f.get("size"),
                "content_type": f.get("content-type") or f.get("content_type"),
                "updated_at": f.get("updated_at"),
            })

        return _json({"total_count": len(results), "files": results})
    except Exception as exc:
        return _json({"error": _safe_error(exc)})


@mcp.tool()
def download_selected_files(
    ctx: Context,
    file_ids: list[int],
    destination: str,
) -> str:
    """Download a batch of specific Canvas files to a local directory.

    Skips files that already exist at the destination (safe to re-run).

    Args:
        file_ids: List of Canvas file IDs to download (from search_course_files).
        destination: Local directory path to save files to. ~ is expanded.
    """
    try:
        if not destination or not destination.strip():
            return _json({"error": "destination must be a non-empty path."})

        app = _get_ctx(ctx)
        dest_dir = Path(destination).expanduser()
        dest_dir.mkdir(parents=True, exist_ok=True)

        downloaded: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        for file_id in file_ids:
            try:
                file_info = app.client.get_file(file_id)
                filename = file_info.get("display_name") or file_info.get("filename") or f"file-{file_id}"
                download_url = file_info.get("url") or ""

                if not download_url:
                    failed.append({
                        "file_id": file_id,
                        "filename": filename,
                        "local_path": None,
                        "status": "failed",
                        "error": "No download URL available",
                    })
                    continue

                local_path = dest_dir / filename

                if local_path.exists():
                    skipped.append({
                        "file_id": file_id,
                        "filename": filename,
                        "local_path": str(local_path),
                        "status": "skipped",
                    })
                    continue

                bytes_written, _sha256, _etag = app.client.download_file(download_url, local_path)
                downloaded.append({
                    "file_id": file_id,
                    "filename": filename,
                    "local_path": str(local_path),
                    "status": "downloaded",
                    "bytes_written": bytes_written,
                })
            except Exception as exc:
                failed.append({
                    "file_id": file_id,
                    "filename": f"file-{file_id}",
                    "local_path": None,
                    "status": "failed",
                    "error": str(exc),
                })

        return _json({
            "destination": str(dest_dir),
            "downloaded": len(downloaded),
            "skipped": len(skipped),
            "failed": len(failed),
            "files": downloaded + skipped + failed,
        })
    except Exception as exc:
        return _json({"error": _safe_error(exc)})


@mcp.tool()
def set_download_path(
    ctx: Context,
    destination: str,
    course_id: int | None = None,
) -> str:
    """Save a download path to the config file for future use.

    Args:
        destination: Local directory path to persist. ~ is expanded.
        course_id: Optional course ID. If provided, saves a per-course path.
                   If omitted, saves the global default download path.
    """
    try:
        if course_id is not None:
            set_course_path(course_id, destination)
            scope = "course"
        else:
            set_default_destination(destination)
            scope = "global"

        return _json({
            "saved": True,
            "destination": str(Path(destination).expanduser()),
            "course_id": course_id,
            "scope": scope,
        })
    except Exception as exc:
        return _json({"error": _safe_error(exc)})


def _find_course(client: CanvasClient, course_id: int) -> CourseSummary | None:
    courses = client.list_courses(include_all=True)
    for c in courses:
        if c.id == course_id:
            return c
    return None


@mcp.tool()
def sync_course_files(
    ctx: Context,
    course_id: int,
    force: bool = False,
    sources: list[str] | None = None,
    destination: str | None = None,
) -> str:
    """Sync (download) all files for a Canvas course to the local filesystem.

    Behaves like "git pull" for course files — downloads new/changed files and
    skips unchanged ones. Set force=True to re-download everything.

    Args:
        course_id: The Canvas course ID to sync.
        force: If True, overwrite existing files even if unchanged.
        sources: Content sources to include. Defaults to all
                 (files, assignments, discussions, pages, modules).
        destination: Optional local directory path to save files to. ~ is expanded.
                     Overrides the configured course path and default destination.
    """
    try:
        app = _get_ctx(ctx)
        cfg = app.config

        course = _find_course(app.client, course_id)
        if course is None:
            return _json({"error": f"Course {course_id} not found."})

        selected_sources = normalize_sources(sources)

        if destination is not None:
            custom_dest: Path | None = Path(destination).expanduser()
        else:
            custom_dest = get_course_path(course_id, cfg)
        dest_root = cfg.destination_path()

        remote_files, warnings = collect_remote_files_for_course(
            app.client, course_id, selected_sources,
        )

        if not remote_files and not warnings:
            return _json({
                "course_id": course_id,
                "course_name": course.name,
                "message": "No files found for this course.",
            })

        course_slug = build_course_slug(course)

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
            app.client,
            tasks,
            previous_items_by_file_id=previous_by_file_id,
            force=force,
            concurrency=cfg.default_concurrency,
            console=Console(quiet=True),
        )

        manifest_items = [result_to_manifest_item(r) for r in results]
        manifest_items.extend(
            warning_to_manifest_item(w, course_id=course_id) for w in warnings
        )

        run_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        course_payload = {
            "run_id": run_id,
            "base_url": app.base_url,
            "course_id": course_id,
            "sources": selected_sources,
            "started_at": now,
            "completed_at": now,
            "items": manifest_items,
        }

        if custom_dest is not None:
            write_manifest(manifest_file, course_payload)
        else:
            write_course_manifest(dest_root, course_slug, course_payload)

        counts = summarize_results(results)
        result_destination = str(custom_dest) if custom_dest is not None else str(dest_root / course_slug)

        return _json({
            "course_id": course_id,
            "course_name": course.name,
            "destination": result_destination,
            "downloaded": counts["downloaded"],
            "skipped": counts["skipped"],
            "failed": counts["failed"],
            "warnings": len(warnings),
            "total_files": len(remote_files),
            "sources": selected_sources,
            "force": force,
        })
    except Exception as exc:
        return _json({"error": _safe_error(exc)})


@mcp.tool()
def complete_assignment(
    ctx: Context,
    assignment_name: str | None = None,
    assignment_id: int | None = None,
    course_id: int | None = None,
    file_paths: list[str] | None = None,
    text_submission: str | None = None,
    url_submission: str | None = None,
) -> str:
    """Complete or submit an assignment in Canvas.

    When online submission is available and no submission payload is provided,
    this tool responds with `needs_input` and tells the caller what is required.
    If no supported submission path exists, it attempts module item completion.
    """
    try:
        app = _get_ctx(ctx)
        course_ids = [course_id] if course_id else _get_active_course_ids(app.client)
        if not course_ids:
            return _json(
                _build_complete_assignment_response(
                    status="error",
                    action_taken="none",
                    course_id=None,
                    assignment_id=assignment_id,
                    assignment_name=assignment_name,
                    url=None,
                    next_step="No active courses were found.",
                )
            )

        records = _assignment_search_space(app.client, course_ids)
        selected, candidates, error = _select_assignment(
            records,
            assignment_id=assignment_id,
            assignment_name=assignment_name,
        )
        if error:
            status = "ambiguous" if candidates else "not_found"
            return _json(
                _build_complete_assignment_response(
                    status=status,
                    action_taken="none",
                    course_id=course_id,
                    assignment_id=assignment_id,
                    assignment_name=assignment_name,
                    url=None,
                    next_step=error,
                    extra={"candidates": candidates} if candidates else None,
                )
            )

        assert selected is not None
        assignment = selected["assignment"]
        selected_course_id = int(selected["course_id"])
        selected_assignment_id = int(assignment.get("id"))
        selected_assignment_name = str(assignment.get("name") or "")
        assignment_url = assignment.get("html_url")

        provided_kinds = sum(
            1 for value in (file_paths, text_submission, url_submission) if value
        )
        if provided_kinds > 1:
            return _json(
                _build_complete_assignment_response(
                    status="error",
                    action_taken="none",
                    course_id=selected_course_id,
                    assignment_id=selected_assignment_id,
                    assignment_name=selected_assignment_name,
                    url=assignment_url,
                    next_step="Provide only one of: file_paths, text_submission, or url_submission.",
                )
            )

        submission_types = [
            str(item) for item in (assignment.get("submission_types") or [])
        ]
        automatable = sorted(
            item for item in submission_types if item in _AUTOMATED_SUBMISSION_TYPES
        )

        if not file_paths and not text_submission and not url_submission and automatable:
            return _json(
                _build_complete_assignment_response(
                    status="needs_input",
                    action_taken="none",
                    course_id=selected_course_id,
                    assignment_id=selected_assignment_id,
                    assignment_name=selected_assignment_name,
                    url=assignment_url,
                    next_step=(
                        "Provide submission content to complete this assignment. "
                        f"Supported for this assignment: {', '.join(automatable)}"
                    ),
                )
            )

        if file_paths:
            if "online_upload" not in submission_types:
                return _json(
                    _build_complete_assignment_response(
                        status="manual_action",
                        action_taken="none",
                        course_id=selected_course_id,
                        assignment_id=selected_assignment_id,
                        assignment_name=selected_assignment_name,
                        url=assignment_url,
                        next_step=(
                            "This assignment does not accept file uploads. "
                            f"Canvas submission_types: {submission_types}"
                        ),
                    )
                )
            resolved_paths, file_error = _validate_absolute_file_paths(file_paths)
            if file_error:
                return _json(
                    _build_complete_assignment_response(
                        status="error",
                        action_taken="none",
                        course_id=selected_course_id,
                        assignment_id=selected_assignment_id,
                        assignment_name=selected_assignment_name,
                        url=assignment_url,
                        next_step=file_error,
                    )
                )
            file_ids: list[int] = []
            for path in resolved_paths:
                init_payload = app.client.init_assignment_file_upload(
                    selected_course_id,
                    selected_assignment_id,
                    filename=path.name,
                    size=path.stat().st_size,
                )
                upload_url = init_payload.get("upload_url")
                upload_params = init_payload.get("upload_params") or {}
                if not isinstance(upload_url, str) or not upload_url:
                    return _json(
                        _build_complete_assignment_response(
                            status="error",
                            action_taken="none",
                            course_id=selected_course_id,
                            assignment_id=selected_assignment_id,
                            assignment_name=selected_assignment_name,
                            url=assignment_url,
                            next_step=f"Canvas did not provide upload_url for {path.name}.",
                        )
                    )
                uploaded = app.client.upload_file_to_canvas(upload_url, upload_params, path)
                uploaded_id = uploaded.get("id")
                if not isinstance(uploaded_id, int):
                    return _json(
                        _build_complete_assignment_response(
                            status="error",
                            action_taken="none",
                            course_id=selected_course_id,
                            assignment_id=selected_assignment_id,
                            assignment_name=selected_assignment_name,
                            url=assignment_url,
                            next_step=f"Canvas upload did not return a file id for {path.name}.",
                        )
                    )
                file_ids.append(uploaded_id)
            submission = app.client.submit_assignment(
                selected_course_id,
                selected_assignment_id,
                submission_type="online_upload",
                body={"file_ids": file_ids},
            )
            return _json(
                _build_complete_assignment_response(
                    status="completed",
                    action_taken="submitted_online_upload",
                    course_id=selected_course_id,
                    assignment_id=selected_assignment_id,
                    assignment_name=selected_assignment_name,
                    url=assignment_url,
                    extra={"submission": submission},
                )
            )

        if text_submission:
            if "online_text_entry" not in submission_types:
                return _json(
                    _build_complete_assignment_response(
                        status="manual_action",
                        action_taken="none",
                        course_id=selected_course_id,
                        assignment_id=selected_assignment_id,
                        assignment_name=selected_assignment_name,
                        url=assignment_url,
                        next_step=(
                            "This assignment does not accept text entry submissions. "
                            f"Canvas submission_types: {submission_types}"
                        ),
                    )
                )
            submission = app.client.submit_assignment(
                selected_course_id,
                selected_assignment_id,
                submission_type="online_text_entry",
                body={"body": text_submission},
            )
            return _json(
                _build_complete_assignment_response(
                    status="completed",
                    action_taken="submitted_online_text_entry",
                    course_id=selected_course_id,
                    assignment_id=selected_assignment_id,
                    assignment_name=selected_assignment_name,
                    url=assignment_url,
                    extra={"submission": submission},
                )
            )

        if url_submission:
            if "online_url" not in submission_types:
                return _json(
                    _build_complete_assignment_response(
                        status="manual_action",
                        action_taken="none",
                        course_id=selected_course_id,
                        assignment_id=selected_assignment_id,
                        assignment_name=selected_assignment_name,
                        url=assignment_url,
                        next_step=(
                            "This assignment does not accept URL submissions. "
                            f"Canvas submission_types: {submission_types}"
                        ),
                    )
                )
            submission = app.client.submit_assignment(
                selected_course_id,
                selected_assignment_id,
                submission_type="online_url",
                body={"url": url_submission},
            )
            return _json(
                _build_complete_assignment_response(
                    status="completed",
                    action_taken="submitted_online_url",
                    course_id=selected_course_id,
                    assignment_id=selected_assignment_id,
                    assignment_name=selected_assignment_name,
                    url=assignment_url,
                    extra={"submission": submission},
                )
            )

        module_item = _resolve_module_item_for_assignment(
            app.client,
            course_id=selected_course_id,
            assignment_id=selected_assignment_id,
        )
        if module_item:
            module_id, module_item_id = module_item
            done_payload = app.client.mark_module_item_done(
                selected_course_id,
                module_id,
                module_item_id,
            )
            return _json(
                _build_complete_assignment_response(
                    status="completed",
                    action_taken="marked_module_item_done",
                    course_id=selected_course_id,
                    assignment_id=selected_assignment_id,
                    assignment_name=selected_assignment_name,
                    url=assignment_url,
                    extra={
                        "module_id": module_id,
                        "module_item_id": module_item_id,
                        "result": done_payload,
                    },
                )
            )

        return _json(
            _build_complete_assignment_response(
                status="manual_action",
                action_taken="none",
                course_id=selected_course_id,
                assignment_id=selected_assignment_id,
                assignment_name=selected_assignment_name,
                url=assignment_url,
                next_step=(
                    "No supported submission payload was provided and module completion "
                    "was not available. Open the assignment URL to complete it manually."
                ),
            )
        )
    except Exception as exc:
        return _json(
            _build_complete_assignment_response(
                status="error",
                action_taken="none",
                course_id=course_id,
                assignment_id=assignment_id,
                assignment_name=assignment_name,
                url=None,
                next_step=_safe_error(exc),
            )
        )


def main() -> None:
    """Entry point for the Canvas MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
