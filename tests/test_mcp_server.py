"""Tests for the MCP server tools.

Each tool is a plain sync function that receives a context object. We mock the
CanvasClient inside the context so no real HTTP calls are made.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from canvasctl.canvas_api import (
    Announcement,
    AssignmentGrade,
    CalendarEvent,
    CourseGrade,
    CourseSummary,
    UpcomingAssignment,
)
from canvasctl.config import AppConfig
from canvasctl.mcp_server import (
    AppContext,
    _convert_tz,
    _localize_dates,
    _strip_html,
    complete_assignment,
    download_file,
    download_selected_files,
    get_announcements,
    get_calendar_events,
    get_grades_detailed,
    get_grades_summary,
    get_syllabus,
    get_upcoming_assignments,
    list_course_files,
    list_courses,
    search_course_files,
    set_download_path,
    sync_course_files,
)


def _make_ctx(
    client: Any,
    timezone: ZoneInfo | None = None,
    config: AppConfig | None = None,
) -> Any:
    """Build a fake MCP context wrapping a mock CanvasClient."""
    app = AppContext(
        client=client,
        base_url="https://canvas.test",
        config=config or AppConfig(),
        timezone=timezone,
    )
    # MCP tools access ctx.request_context.lifespan_context
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app
    return ctx


class TestStripHtml:
    def test_basic(self):
        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_empty(self):
        assert _strip_html("") == ""

    def test_no_tags(self):
        assert _strip_html("plain text") == "plain text"

    def test_nested_tags(self):
        result = _strip_html("<div><ul><li>Item 1</li><li>Item 2</li></ul></div>")
        assert "Item 1" in result
        assert "Item 2" in result


class TestListCourses:
    def test_returns_courses(self):
        client = MagicMock()
        client.list_courses.return_value = [
            CourseSummary(
                id=100,
                course_code="BIO101",
                name="Biology",
                workflow_state="available",
                term_name="Spring 2025",
                start_at=None,
                end_at=None,
            ),
        ]
        ctx = _make_ctx(client)

        result = json.loads(list_courses(ctx, include_all=False))
        assert len(result) == 1
        assert result[0]["id"] == 100
        assert result[0]["course_code"] == "BIO101"
        client.list_courses.assert_called_once_with(include_all=False)

    def test_error(self):
        client = MagicMock()
        client.list_courses.side_effect = RuntimeError("API down")
        ctx = _make_ctx(client)

        result = json.loads(list_courses(ctx))
        assert "error" in result
        assert "API down" in result["error"]


class TestGetUpcomingAssignments:
    def test_filters_by_date(self):
        client = MagicMock()
        client.list_courses.return_value = [
            CourseSummary(
                id=100, course_code="BIO101", name="Biology",
                workflow_state="available", term_name=None,
                start_at=None, end_at=None,
            ),
        ]
        client.list_upcoming_assignments.return_value = [
            UpcomingAssignment(
                assignment_id=1,
                assignment_name="Homework 1",
                course_id=100,
                course_name="Biology",
                due_at="2099-06-01T23:59:00Z",  # far future => within any days_ahead
                lock_at=None,
                unlock_at=None,
                points_possible=100.0,
                submission_types=["online_upload"],
                has_submitted=False,
                html_url="https://canvas.test/courses/100/assignments/1",
            ),
            UpcomingAssignment(
                assignment_id=2,
                assignment_name="Past HW",
                course_id=100,
                course_name="Biology",
                due_at="2020-01-01T00:00:00Z",  # past => filtered out
                lock_at=None,
                unlock_at=None,
                points_possible=50.0,
                submission_types=["online_text_entry"],
                has_submitted=True,
                html_url=None,
            ),
        ]
        ctx = _make_ctx(client)

        result = json.loads(get_upcoming_assignments(ctx, days_ahead=36500))
        # Only the future assignment should remain (past one filtered out)
        assert len(result) == 1
        assert result[0]["assignment_name"] == "Homework 1"

    def test_specific_course_id(self):
        client = MagicMock()
        client.list_upcoming_assignments.return_value = [
            UpcomingAssignment(
                assignment_id=1,
                assignment_name="HW",
                course_id=200,
                course_name="Math",
                due_at="2099-12-31T23:59:00Z",
                lock_at=None,
                unlock_at=None,
                points_possible=10.0,
                submission_types=[],
                has_submitted=False,
                html_url=None,
            ),
        ]
        ctx = _make_ctx(client)

        result = json.loads(get_upcoming_assignments(ctx, course_id=200, days_ahead=36500))
        assert len(result) == 1
        # Should NOT call list_courses when course_id is provided
        client.list_courses.assert_not_called()

    def test_no_due_date_skipped(self):
        client = MagicMock()
        client.list_upcoming_assignments.return_value = [
            UpcomingAssignment(
                assignment_id=1,
                assignment_name="No Due",
                course_id=100,
                course_name="Bio",
                due_at=None,
                lock_at=None,
                unlock_at=None,
                points_possible=None,
                submission_types=[],
                has_submitted=False,
                html_url=None,
            ),
        ]
        ctx = _make_ctx(client)

        result = json.loads(get_upcoming_assignments(ctx, course_id=100))
        assert result == []


class TestGetAnnouncements:
    def test_returns_announcements(self):
        client = MagicMock()
        client.list_courses.return_value = [
            CourseSummary(
                id=100, course_code="BIO101", name="Biology",
                workflow_state="available", term_name=None,
                start_at=None, end_at=None,
            ),
        ]
        client.list_announcements.return_value = [
            Announcement(
                id=10,
                title="Welcome",
                message="<p>Hello</p>",
                course_id=100,
                posted_at="2025-01-10T10:00:00Z",
                author_name="Prof Smith",
            ),
        ]
        ctx = _make_ctx(client)

        result = json.loads(get_announcements(ctx))
        assert len(result) == 1
        assert result[0]["title"] == "Welcome"

    def test_limit(self):
        client = MagicMock()
        client.list_announcements.return_value = [
            Announcement(id=i, title=f"A{i}", message="", course_id=100,
                         posted_at=None, author_name=None)
            for i in range(20)
        ]
        ctx = _make_ctx(client)

        result = json.loads(get_announcements(ctx, course_id=100, limit=5))
        assert len(result) == 5


class TestGetCalendarEvents:
    def test_returns_events(self):
        client = MagicMock()
        client.list_calendar_events.return_value = [
            CalendarEvent(
                id=50,
                title="Midterm",
                description="Chapters 1-5",
                start_at="2025-03-15T09:00:00Z",
                end_at="2025-03-15T11:00:00Z",
                event_type="event",
                context_name="Biology 101",
            ),
        ]
        ctx = _make_ctx(client)

        result = json.loads(get_calendar_events(ctx, course_id=100))
        assert len(result) == 1
        assert result[0]["title"] == "Midterm"


class TestGetSyllabus:
    def test_returns_syllabus_with_text(self):
        client = MagicMock()
        client.get_course_syllabus.return_value = {
            "id": 100,
            "name": "Biology 101",
            "syllabus_body": "<h1>Syllabus</h1><p>Welcome to Biology.</p>",
        }
        ctx = _make_ctx(client)

        result = json.loads(get_syllabus(ctx, course_id=100))
        assert result["course_id"] == 100
        assert result["course_name"] == "Biology 101"
        assert "<h1>" in result["syllabus_body"]
        assert "Syllabus" in result["syllabus_body_text"]
        assert "<h1>" not in result["syllabus_body_text"]

    def test_empty_syllabus(self):
        client = MagicMock()
        client.get_course_syllabus.return_value = {
            "id": 100,
            "name": "Empty Course",
            "syllabus_body": None,
        }
        ctx = _make_ctx(client)

        result = json.loads(get_syllabus(ctx, course_id=100))
        assert result["syllabus_body"] == ""
        assert result["syllabus_body_text"] == ""


class TestGetGradesSummary:
    def test_returns_all(self):
        client = MagicMock()
        client.list_courses_with_grades.return_value = [
            CourseGrade(
                course_id=100, course_code="BIO101", course_name="Biology",
                current_score=92.5, current_grade="A-",
            ),
            CourseGrade(
                course_id=200, course_code="MATH201", course_name="Calculus",
                current_score=None, current_grade=None,
            ),
        ]
        ctx = _make_ctx(client)

        result = json.loads(get_grades_summary(ctx))
        assert len(result) == 2

    def test_filter_by_course_id(self):
        client = MagicMock()
        client.list_courses_with_grades.return_value = [
            CourseGrade(
                course_id=100, course_code="BIO101", course_name="Biology",
                current_score=92.5, current_grade="A-",
            ),
            CourseGrade(
                course_id=200, course_code="MATH201", course_name="Calculus",
                current_score=85.0, current_grade="B",
            ),
        ]
        ctx = _make_ctx(client)

        result = json.loads(get_grades_summary(ctx, course_id=100))
        assert len(result) == 1
        assert result[0]["course_id"] == 100


class TestGetGradesDetailed:
    def test_returns_assignments(self):
        client = MagicMock()
        client.list_assignment_grades.return_value = [
            AssignmentGrade(
                assignment_id=10,
                assignment_name="HW1",
                course_id=100,
                points_possible=100.0,
                score=95.0,
                grade="A",
                submitted_at="2025-01-15T10:00:00Z",
                workflow_state="graded",
            ),
        ]
        ctx = _make_ctx(client)

        result = json.loads(get_grades_detailed(ctx, course_id=100))
        assert len(result) == 1
        assert result[0]["score"] == 95.0


class TestListCourseFiles:
    def test_returns_files(self):
        client = MagicMock()
        client.list_course_files.return_value = [
            {"id": 1, "display_name": "syllabus.pdf", "size": 1024},
        ]
        ctx = _make_ctx(client)

        result = json.loads(list_course_files(ctx, course_id=100))
        assert len(result) == 1
        assert result[0]["display_name"] == "syllabus.pdf"


class TestDownloadFile:
    def test_success(self, tmp_path):
        client = MagicMock()
        client.get_file.return_value = {
            "id": 42,
            "display_name": "notes.pdf",
            "url": "https://canvas.test/files/42/download",
        }
        client.download_file.return_value = (2048, "abc123sha", None)
        ctx = _make_ctx(client)

        dest = str(tmp_path / "notes.pdf")
        result = json.loads(download_file(ctx, file_id=42, destination=dest))
        assert result["file_id"] == 42
        assert result["bytes_written"] == 2048
        assert result["destination"] == dest

    def test_no_download_url(self):
        client = MagicMock()
        client.get_file.return_value = {
            "id": 42,
            "display_name": "notes.pdf",
            "url": "",
        }
        ctx = _make_ctx(client)

        result = json.loads(download_file(ctx, file_id=42))
        assert "error" in result
        assert "No download URL" in result["error"]

    def test_error(self):
        client = MagicMock()
        client.get_file.side_effect = RuntimeError("not found")
        ctx = _make_ctx(client)

        result = json.loads(download_file(ctx, file_id=999))
        assert "error" in result


class TestConvertTz:
    def test_none_returns_none(self):
        tz = ZoneInfo("America/Los_Angeles")
        assert _convert_tz(None, tz) is None

    def test_utc_to_pacific(self):
        # 2026-02-27T07:59:00Z => 2026-02-26T23:59:00-08:00 (PST)
        result = _convert_tz("2026-02-27T07:59:00Z", ZoneInfo("America/Los_Angeles"))
        assert result is not None
        assert result.startswith("2026-02-26T23:59:00")
        assert "-08:00" in result

    def test_utc_to_eastern(self):
        # 2026-06-15T04:00:00Z => 2026-06-15T00:00:00-04:00 (EDT)
        result = _convert_tz("2026-06-15T04:00:00Z", ZoneInfo("America/New_York"))
        assert result is not None
        assert result.startswith("2026-06-15T00:00:00")
        assert "-04:00" in result

    def test_invalid_string_returned_as_is(self):
        tz = ZoneInfo("America/Los_Angeles")
        assert _convert_tz("not-a-date", tz) == "not-a-date"


class TestLocalizeDates:
    def test_converts_specified_keys(self):
        tz = ZoneInfo("America/Los_Angeles")
        obj = {
            "due_at": "2026-02-27T07:59:00Z",
            "lock_at": None,
            "name": "HW1",
        }
        result = _localize_dates(obj, tz, ("due_at", "lock_at"))
        assert result["due_at"].startswith("2026-02-26T23:59:00")
        assert result["lock_at"] is None
        assert result["name"] == "HW1"

    def test_missing_key_ignored(self):
        tz = ZoneInfo("America/Los_Angeles")
        obj = {"name": "test"}
        result = _localize_dates(obj, tz, ("due_at",))
        assert result == {"name": "test"}


class TestTimezoneIntegration:
    """Test that tools convert dates when timezone is configured."""

    def test_upcoming_assignments_converts_dates(self):
        client = MagicMock()
        client.list_upcoming_assignments.return_value = [
            UpcomingAssignment(
                assignment_id=1,
                assignment_name="HW",
                course_id=100,
                course_name="Bio",
                due_at="2099-06-01T06:59:00Z",
                lock_at="2099-06-01T07:00:00Z",
                unlock_at=None,
                points_possible=10.0,
                submission_types=[],
                has_submitted=False,
                html_url=None,
            ),
        ]
        tz = ZoneInfo("America/Los_Angeles")
        ctx = _make_ctx(client, timezone=tz)

        result = json.loads(get_upcoming_assignments(ctx, course_id=100, days_ahead=36500))
        assert len(result) == 1
        # UTC 06:59 => Pacific 23:59 previous day (PDT, -07:00 in June)
        assert "2099-05-31T23:59:00" in result[0]["due_at"]
        assert "-07:00" in result[0]["due_at"]
        assert result[0]["lock_at"] is not None
        assert "-07:00" in result[0]["lock_at"]
        assert result[0]["unlock_at"] is None

    def test_announcements_converts_posted_at(self):
        client = MagicMock()
        client.list_announcements.return_value = [
            Announcement(
                id=10,
                title="News",
                message="hi",
                course_id=100,
                posted_at="2026-01-15T18:00:00Z",
                author_name="Prof",
            ),
        ]
        tz = ZoneInfo("America/Los_Angeles")
        ctx = _make_ctx(client, timezone=tz)

        result = json.loads(get_announcements(ctx, course_id=100))
        assert len(result) == 1
        # UTC 18:00 Jan 15 => PST 10:00 Jan 15
        assert "2026-01-15T10:00:00" in result[0]["posted_at"]
        assert "-08:00" in result[0]["posted_at"]

    def test_no_timezone_passes_through(self):
        """When timezone is None, dates are returned as-is."""
        client = MagicMock()
        client.list_announcements.return_value = [
            Announcement(
                id=10, title="News", message="hi", course_id=100,
                posted_at="2026-01-15T18:00:00Z", author_name="Prof",
            ),
        ]
        ctx = _make_ctx(client, timezone=None)

        result = json.loads(get_announcements(ctx, course_id=100))
        assert result[0]["posted_at"] == "2026-01-15T18:00:00Z"


_SYNC_PREFIX = "canvasctl.mcp_server"

_BIO_COURSE = CourseSummary(
    id=100,
    course_code="BIO101",
    name="Biology",
    workflow_state="available",
    term_name="Spring 2025",
    start_at=None,
    end_at=None,
)


class TestSyncCourseFiles:
    def test_sync_success(self, tmp_path):
        client = MagicMock()
        client.list_courses.return_value = [_BIO_COURSE]
        cfg = AppConfig(default_dest=str(tmp_path))
        ctx = _make_ctx(client, config=cfg)

        fake_remote = MagicMock()
        fake_remote.file_id = 1

        fake_result = MagicMock()
        fake_result.status = "downloaded"
        fake_result.task.file.file_id = 1
        fake_result.task.course_id = 100
        fake_result.task.file.display_name = "notes.pdf"
        fake_result.task.file.source_type = "files"
        fake_result.task.file.source_ref = "files:1"
        fake_result.task.file.download_url = "https://canvas.test/files/1"
        fake_result.task.file.size = 1024
        fake_result.task.file.updated_at = None
        fake_result.task.local_path = tmp_path / "bio101-100" / "notes.pdf"
        fake_result.bytes_downloaded = 1024
        fake_result.error = None
        fake_result.sha256 = "abc123"
        fake_result.etag = None

        with (
            patch(f"{_SYNC_PREFIX}.collect_remote_files_for_course", return_value=([fake_remote], [])),
            patch(f"{_SYNC_PREFIX}.plan_course_download_tasks", return_value=[]),
            patch(f"{_SYNC_PREFIX}.download_tasks", return_value=[fake_result]),
            patch(f"{_SYNC_PREFIX}.load_manifest", return_value={}),
            patch(f"{_SYNC_PREFIX}.write_course_manifest"),
        ):
            result = json.loads(sync_course_files(ctx, course_id=100))

        assert result["course_id"] == 100
        assert result["course_name"] == "Biology"
        assert result["downloaded"] == 1
        assert result["skipped"] == 0
        assert result["failed"] == 0
        assert result["total_files"] == 1
        assert "destination" in result

    def test_course_not_found(self):
        client = MagicMock()
        client.list_courses.return_value = []
        ctx = _make_ctx(client)

        result = json.loads(sync_course_files(ctx, course_id=999))
        assert "error" in result
        assert "999" in result["error"]
        assert "not found" in result["error"]

    def test_no_files(self):
        client = MagicMock()
        client.list_courses.return_value = [_BIO_COURSE]
        ctx = _make_ctx(client)

        with patch(f"{_SYNC_PREFIX}.collect_remote_files_for_course", return_value=([], [])):
            result = json.loads(sync_course_files(ctx, course_id=100))

        assert result["course_id"] == 100
        assert "message" in result
        assert "No files" in result["message"]

    def test_force_flag(self, tmp_path):
        client = MagicMock()
        client.list_courses.return_value = [_BIO_COURSE]
        cfg = AppConfig(default_dest=str(tmp_path))
        ctx = _make_ctx(client, config=cfg)

        fake_remote = MagicMock()
        fake_remote.file_id = 1

        with (
            patch(f"{_SYNC_PREFIX}.collect_remote_files_for_course", return_value=([fake_remote], [])),
            patch(f"{_SYNC_PREFIX}.plan_course_download_tasks", return_value=[]),
            patch(f"{_SYNC_PREFIX}.download_tasks", return_value=[]) as mock_dl,
            patch(f"{_SYNC_PREFIX}.load_manifest", return_value={}),
            patch(f"{_SYNC_PREFIX}.write_course_manifest"),
        ):
            sync_course_files(ctx, course_id=100, force=True)

        mock_dl.assert_called_once()
        _, kwargs = mock_dl.call_args
        assert kwargs["force"] is True
class TestCompleteAssignment:
    def test_returns_ambiguous_matches(self):
        client = MagicMock()
        client.list_courses.return_value = [
            CourseSummary(
                id=100,
                course_code="BIO101",
                name="Biology",
                workflow_state="available",
                term_name=None,
                start_at=None,
                end_at=None,
            ),
            CourseSummary(
                id=200,
                course_code="CHEM101",
                name="Chemistry",
                workflow_state="available",
                term_name=None,
                start_at=None,
                end_at=None,
            ),
        ]
        client.list_assignments.side_effect = [
            [{"id": 10, "name": "Homework 1", "submission_types": [], "html_url": "u1"}],
            [{"id": 20, "name": "Homework 1", "submission_types": [], "html_url": "u2"}],
        ]
        ctx = _make_ctx(client)

        result = json.loads(complete_assignment(ctx, assignment_name="Homework 1"))

        assert result["status"] == "ambiguous"
        assert len(result["candidates"]) == 2

    def test_returns_needs_input_for_submission_assignments(self):
        client = MagicMock()
        client.list_courses.return_value = [
            CourseSummary(
                id=100,
                course_code="BIO101",
                name="Biology",
                workflow_state="available",
                term_name=None,
                start_at=None,
                end_at=None,
            ),
        ]
        client.list_assignments.return_value = [
            {
                "id": 10,
                "name": "Homework 1",
                "submission_types": ["online_upload"],
                "html_url": "https://canvas.test/courses/100/assignments/10",
            }
        ]
        ctx = _make_ctx(client)

        result = json.loads(complete_assignment(ctx, assignment_name="Homework 1"))

        assert result["status"] == "needs_input"
        assert result["action_taken"] == "none"
        assert "online_upload" in result["next_step"]

    def test_submits_text_assignment(self):
        client = MagicMock()
        client.list_assignments.return_value = [
            {
                "id": 10,
                "name": "Reflection",
                "submission_types": ["online_text_entry"],
                "html_url": "https://canvas.test/courses/100/assignments/10",
            }
        ]
        client.submit_assignment.return_value = {"id": 333, "workflow_state": "submitted"}
        ctx = _make_ctx(client)

        result = json.loads(
            complete_assignment(
                ctx,
                assignment_name="Reflection",
                course_id=100,
                text_submission="Done.",
            )
        )

        assert result["status"] == "completed"
        assert result["action_taken"] == "submitted_online_text_entry"
        client.submit_assignment.assert_called_once_with(
            100,
            10,
            submission_type="online_text_entry",
            body={"body": "Done."},
        )

    def test_marks_module_done_when_no_submission_types(self):
        client = MagicMock()
        client.list_assignments.return_value = [
            {
                "id": 10,
                "name": "Reading Check",
                "submission_types": ["none"],
                "html_url": "https://canvas.test/courses/100/assignments/10",
            }
        ]
        client.list_modules.return_value = [
            {
                "id": 5,
                "items": [{"id": 55, "type": "Assignment", "content_id": 10}],
            }
        ]
        client.mark_module_item_done.return_value = {"done": True}
        ctx = _make_ctx(client)

        result = json.loads(
            complete_assignment(ctx, assignment_name="Reading Check", course_id=100)
        )

        assert result["status"] == "completed"
        assert result["action_taken"] == "marked_module_item_done"
        client.mark_module_item_done.assert_called_once_with(100, 5, 55)

    def test_returns_manual_action_when_no_automation_available(self):
        client = MagicMock()
        client.list_assignments.return_value = [
            {
                "id": 10,
                "name": "Paper",
                "submission_types": ["none"],
                "html_url": "https://canvas.test/courses/100/assignments/10",
            }
        ]
        client.list_modules.return_value = []
        ctx = _make_ctx(client)

        result = json.loads(complete_assignment(ctx, assignment_name="Paper", course_id=100))

        assert result["status"] == "manual_action"
        assert result["url"] == "https://canvas.test/courses/100/assignments/10"

    def test_upload_submission_uses_absolute_paths(self, tmp_path):
        local_file = tmp_path / "homework.py"
        local_file.write_text("print('ok')\n", encoding="utf-8")

        client = MagicMock()
        client.list_assignments.return_value = [
            {
                "id": 10,
                "name": "Code HW",
                "submission_types": ["online_upload"],
                "html_url": "https://canvas.test/courses/100/assignments/10",
            }
        ]
        client.init_assignment_file_upload.return_value = {
            "upload_url": "https://upload.canvas.test",
            "upload_params": {"token": "abc"},
        }
        client.upload_file_to_canvas.return_value = {"id": 7001}
        client.submit_assignment.return_value = {"id": 9001}
        ctx = _make_ctx(client)

        result = json.loads(
            complete_assignment(
                ctx,
                assignment_name="Code HW",
                course_id=100,
                file_paths=[str(local_file.resolve())],
            )
        )

        assert result["status"] == "completed"
        assert result["action_taken"] == "submitted_online_upload"
        client.submit_assignment.assert_called_once_with(
            100,
            10,
            submission_type="online_upload",
            body={"file_ids": [7001]},
        )


_SAMPLE_FILES = [
    {
        "id": 1,
        "display_name": "Lecture 1.pdf",
        "filename": "lecture_1.pdf",
        "folder_id": 10,
        "size": 1024,
        "content-type": "application/pdf",
        "updated_at": "2025-01-10T12:00:00Z",
    },
    {
        "id": 2,
        "display_name": "Notes.docx",
        "filename": "notes.docx",
        "folder_id": 10,
        "size": 512,
        "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "updated_at": "2025-01-11T12:00:00Z",
    },
    {
        "id": 3,
        "display_name": "Syllabus.pdf",
        "filename": "syllabus.pdf",
        "folder_id": 20,
        "size": 256,
        "content-type": "application/pdf",
        "updated_at": "2025-01-01T10:00:00Z",
    },
]

_SAMPLE_FOLDERS = {10: "course files/lectures", 20: "course files"}


class TestSearchCourseFiles:
    def _make_client(self):
        client = MagicMock()
        client.list_course_files.return_value = _SAMPLE_FILES
        client.list_course_folders.return_value = _SAMPLE_FOLDERS
        return client

    def test_no_filters_returns_all(self):
        ctx = _make_ctx(self._make_client())
        result = json.loads(search_course_files(ctx, course_id=100))
        assert result["total_count"] == 3
        assert len(result["files"]) == 3

    def test_query_filter_by_name(self):
        ctx = _make_ctx(self._make_client())
        result = json.loads(search_course_files(ctx, course_id=100, query="lecture"))
        assert result["total_count"] == 1
        assert result["files"][0]["display_name"] == "Lecture 1.pdf"

    def test_file_type_filter(self):
        ctx = _make_ctx(self._make_client())
        result = json.loads(search_course_files(ctx, course_id=100, file_type="pdf"))
        assert result["total_count"] == 2
        names = [f["display_name"] for f in result["files"]]
        assert "Lecture 1.pdf" in names
        assert "Syllabus.pdf" in names

    def test_file_type_filter_with_leading_dot(self):
        ctx = _make_ctx(self._make_client())
        result = json.loads(search_course_files(ctx, course_id=100, file_type=".docx"))
        assert result["total_count"] == 1
        assert result["files"][0]["display_name"] == "Notes.docx"

    def test_folder_filter(self):
        ctx = _make_ctx(self._make_client())
        result = json.loads(search_course_files(ctx, course_id=100, folder="lectures"))
        assert result["total_count"] == 2
        ids = [f["file_id"] for f in result["files"]]
        assert 1 in ids
        assert 2 in ids

    def test_case_insensitive(self):
        ctx = _make_ctx(self._make_client())
        result = json.loads(search_course_files(ctx, course_id=100, file_type="PDF"))
        assert result["total_count"] == 2

    def test_no_results(self):
        ctx = _make_ctx(self._make_client())
        result = json.loads(search_course_files(ctx, course_id=100, query="nonexistent"))
        assert result["total_count"] == 0
        assert result["files"] == []

    def test_error(self):
        client = MagicMock()
        client.list_course_files.side_effect = RuntimeError("API error")
        ctx = _make_ctx(client)
        result = json.loads(search_course_files(ctx, course_id=100))
        assert "error" in result


class TestDownloadSelectedFiles:
    def test_download_success(self, tmp_path):
        client = MagicMock()
        client.get_file.return_value = {
            "display_name": "notes.pdf",
            "url": "https://canvas.test/files/1/download",
        }
        client.download_file.return_value = (1024, "sha256abc", None)
        ctx = _make_ctx(client)

        result = json.loads(download_selected_files(ctx, file_ids=[1], destination=str(tmp_path)))
        assert result["downloaded"] == 1
        assert result["skipped"] == 0
        assert result["failed"] == 0
        assert result["files"][0]["status"] == "downloaded"
        assert result["files"][0]["bytes_written"] == 1024

    def test_skip_existing(self, tmp_path):
        existing = tmp_path / "notes.pdf"
        existing.write_text("exists", encoding="utf-8")

        client = MagicMock()
        client.get_file.return_value = {
            "display_name": "notes.pdf",
            "url": "https://canvas.test/files/1/download",
        }
        ctx = _make_ctx(client)

        result = json.loads(download_selected_files(ctx, file_ids=[1], destination=str(tmp_path)))
        assert result["downloaded"] == 0
        assert result["skipped"] == 1
        assert result["files"][0]["status"] == "skipped"
        client.download_file.assert_not_called()

    def test_invalid_destination(self):
        client = MagicMock()
        ctx = _make_ctx(client)

        result = json.loads(download_selected_files(ctx, file_ids=[1], destination=""))
        assert "error" in result

    def test_partial_failure(self, tmp_path):
        client = MagicMock()

        def get_file_side_effect(file_id):
            if file_id == 1:
                return {"display_name": "ok.pdf", "url": "https://canvas.test/files/1/download"}
            raise RuntimeError("not found")

        client.get_file.side_effect = get_file_side_effect
        client.download_file.return_value = (512, "sha", None)
        ctx = _make_ctx(client)

        result = json.loads(download_selected_files(ctx, file_ids=[1, 2], destination=str(tmp_path)))
        assert result["downloaded"] == 1
        assert result["failed"] == 1
        statuses = {f["file_id"]: f["status"] for f in result["files"]}
        assert statuses[1] == "downloaded"
        assert statuses[2] == "failed"

    def test_no_download_url(self, tmp_path):
        client = MagicMock()
        client.get_file.return_value = {"display_name": "missing.pdf", "url": ""}
        ctx = _make_ctx(client)

        result = json.loads(download_selected_files(ctx, file_ids=[5], destination=str(tmp_path)))
        assert result["failed"] == 1
        assert "No download URL" in result["files"][0]["error"]

    def test_error(self):
        client = MagicMock()
        client.get_file.side_effect = RuntimeError("boom")
        ctx = _make_ctx(client)

        result = json.loads(download_selected_files(ctx, file_ids=[1], destination="/tmp/test"))
        assert result["failed"] == 1


class TestSetDownloadPath:
    def test_set_global_path(self, tmp_path):
        ctx = _make_ctx(MagicMock())
        with patch("canvasctl.mcp_server.set_default_destination") as mock_set:
            result = json.loads(set_download_path(ctx, destination=str(tmp_path)))
        mock_set.assert_called_once_with(str(tmp_path))
        assert result["saved"] is True
        assert result["scope"] == "global"
        assert result["course_id"] is None

    def test_set_course_path(self, tmp_path):
        ctx = _make_ctx(MagicMock())
        with patch("canvasctl.mcp_server.set_course_path") as mock_set:
            result = json.loads(set_download_path(ctx, destination=str(tmp_path), course_id=100))
        mock_set.assert_called_once_with(100, str(tmp_path))
        assert result["saved"] is True
        assert result["scope"] == "course"
        assert result["course_id"] == 100

    def test_config_error(self):
        ctx = _make_ctx(MagicMock())
        with patch("canvasctl.mcp_server.set_default_destination", side_effect=ValueError("bad path")):
            result = json.loads(set_download_path(ctx, destination=""))
        assert "error" in result


class TestSyncCourseFilesWithDestination:
    def test_custom_destination_overrides_config(self, tmp_path):
        client = MagicMock()
        client.list_courses.return_value = [_BIO_COURSE]
        cfg = AppConfig(default_dest=str(tmp_path / "default"))
        ctx = _make_ctx(client, config=cfg)

        custom = str(tmp_path / "custom")
        fake_remote = MagicMock()
        fake_remote.file_id = 1

        with (
            patch(f"{_SYNC_PREFIX}.collect_remote_files_for_course", return_value=([fake_remote], [])),
            patch(f"{_SYNC_PREFIX}.plan_course_download_tasks", return_value=[]) as mock_plan,
            patch(f"{_SYNC_PREFIX}.download_tasks", return_value=[]),
            patch(f"{_SYNC_PREFIX}.load_manifest", return_value={}),
            patch(f"{_SYNC_PREFIX}.write_manifest"),
        ):
            result = json.loads(sync_course_files(ctx, course_id=100, destination=custom))

        assert result["destination"] == custom
        _, kwargs = mock_plan.call_args
        assert kwargs["course_dest"] is not None
        assert str(kwargs["course_dest"]) == custom
