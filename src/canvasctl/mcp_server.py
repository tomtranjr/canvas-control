"""Canvas MCP server — exposes Canvas LMS data via Model Context Protocol."""

from __future__ import annotations

import json
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from canvasctl.canvas_api import CanvasClient
from canvasctl.config import load_config


@dataclass
class AppContext:
    client: CanvasClient
    base_url: str


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    token = os.environ.get("CANVAS_TOKEN", "")
    if not token:
        raise RuntimeError(
            "CANVAS_TOKEN environment variable is required. "
            "Set it to your Canvas API access token."
        )

    base_url = os.environ.get("CANVAS_BASE_URL", "")
    if not base_url:
        try:
            cfg = load_config()
            base_url = cfg.base_url or ""
        except Exception:
            pass
    if not base_url:
        raise RuntimeError(
            "CANVAS_BASE_URL environment variable or config base_url is required. "
            "Set it to your Canvas instance URL (e.g. https://school.instructure.com)."
        )

    client = CanvasClient(base_url, token)
    try:
        yield AppContext(client=client, base_url=base_url)
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
        return _json([asdict(c) for c in courses])
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
                    results.append(asdict(a))

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
        return _json([asdict(e) for e in events])
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
        return _json([asdict(g) for g in grades])
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


def main() -> None:
    """Entry point for the Canvas MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
