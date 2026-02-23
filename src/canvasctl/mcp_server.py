"""Canvas MCP server — exposes Canvas LMS data via Model Context Protocol."""

from __future__ import annotations

import json
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
from canvasctl.config import AppConfig, get_course_path, load_config
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
from canvasctl.sources import collect_remote_files_for_course, normalize_sources, warning_to_manifest_item


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
    except Exception:
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
        return _json({"error": str(exc)})


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
        return _json({"error": str(exc)})


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
        return _json({"error": str(exc)})


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
        return _json({"error": str(exc)})


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
        return _json({"error": str(exc)})


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
        return _json({"error": str(exc)})


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
        return _json({"error": str(exc)})


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
        return _json({"error": str(exc)})


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
        return _json({"error": str(exc)})


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
) -> str:
    """Sync (download) all files for a Canvas course to the local filesystem.

    Behaves like "git pull" for course files — downloads new/changed files and
    skips unchanged ones. Set force=True to re-download everything.

    Args:
        course_id: The Canvas course ID to sync.
        force: If True, overwrite existing files even if unchanged.
        sources: Content sources to include. Defaults to all
                 (files, assignments, discussions, pages, modules).
    """
    try:
        app = _get_ctx(ctx)
        cfg = app.config

        course = _find_course(app.client, course_id)
        if course is None:
            return _json({"error": f"Course {course_id} not found."})

        selected_sources = normalize_sources(sources)

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
        destination = str(custom_dest) if custom_dest is not None else str(dest_root / course_slug)

        return _json({
            "course_id": course_id,
            "course_name": course.name,
            "destination": destination,
            "downloaded": counts["downloaded"],
            "skipped": counts["skipped"],
            "failed": counts["failed"],
            "warnings": len(warnings),
            "total_files": len(remote_files),
            "sources": selected_sources,
            "force": force,
        })
    except Exception as exc:
        return _json({"error": str(exc)})


def main() -> None:
    """Entry point for the Canvas MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
