from __future__ import annotations

import pytest
import respx

from canvasctl.canvas_api import CanvasClient


def test_list_upcoming_assignments(monkeypatch):
    monkeypatch.setattr("canvasctl.canvas_api.time.sleep", lambda _: None)

    with respx.mock(assert_all_called=True) as router:
        router.get("https://canvas.test/api/v1/courses/100").respond(
            200,
            json={"id": 100, "name": "Biology 101"},
        )
        router.get("https://canvas.test/api/v1/courses/100/assignments").respond(
            200,
            json=[
                {
                    "id": 1,
                    "name": "Homework 1",
                    "due_at": "2025-03-01T23:59:00Z",
                    "lock_at": None,
                    "unlock_at": "2025-02-15T00:00:00Z",
                    "points_possible": 100.0,
                    "submission_types": ["online_upload"],
                    "html_url": "https://canvas.test/courses/100/assignments/1",
                    "submission": {
                        "workflow_state": "submitted",
                    },
                },
                {
                    "id": 2,
                    "name": "Quiz 1",
                    "due_at": "2025-03-05T23:59:00Z",
                    "lock_at": None,
                    "unlock_at": None,
                    "points_possible": 50.0,
                    "submission_types": ["online_quiz"],
                    "html_url": "https://canvas.test/courses/100/assignments/2",
                    "submission": None,
                },
            ],
        )

        with CanvasClient("https://canvas.test", "token") as client:
            assignments = client.list_upcoming_assignments(100)

    assert len(assignments) == 2
    assert assignments[0].assignment_id == 1
    assert assignments[0].assignment_name == "Homework 1"
    assert assignments[0].course_name == "Biology 101"
    assert assignments[0].has_submitted is True
    assert assignments[0].submission_types == ["online_upload"]
    assert assignments[1].assignment_id == 2
    assert assignments[1].has_submitted is False


def test_list_upcoming_assignments_empty(monkeypatch):
    monkeypatch.setattr("canvasctl.canvas_api.time.sleep", lambda _: None)

    with respx.mock(assert_all_called=True) as router:
        router.get("https://canvas.test/api/v1/courses/100").respond(
            200,
            json={"id": 100, "name": "Empty Course"},
        )
        router.get("https://canvas.test/api/v1/courses/100/assignments").respond(
            200,
            json=[],
        )

        with CanvasClient("https://canvas.test", "token") as client:
            assignments = client.list_upcoming_assignments(100)

    assert assignments == []


def test_list_announcements(monkeypatch):
    monkeypatch.setattr("canvasctl.canvas_api.time.sleep", lambda _: None)

    with respx.mock(assert_all_called=True) as router:
        router.get("https://canvas.test/api/v1/announcements").respond(
            200,
            json=[
                {
                    "id": 10,
                    "title": "Welcome!",
                    "message": "<p>Welcome to the course.</p>",
                    "context_code": "course_100",
                    "posted_at": "2025-01-10T10:00:00Z",
                    "author": {"display_name": "Prof Smith"},
                },
                {
                    "id": 11,
                    "title": "Office Hours",
                    "message": "<p>Changed to Fridays.</p>",
                    "context_code": "course_200",
                    "posted_at": "2025-01-12T14:00:00Z",
                    "author": {"display_name": "Prof Jones"},
                },
            ],
        )

        with CanvasClient("https://canvas.test", "token") as client:
            announcements = client.list_announcements([100, 200])

    assert len(announcements) == 2
    assert announcements[0].id == 10
    assert announcements[0].title == "Welcome!"
    assert announcements[0].course_id == 100
    assert announcements[0].author_name == "Prof Smith"
    assert announcements[1].course_id == 200


def test_list_announcements_empty(monkeypatch):
    monkeypatch.setattr("canvasctl.canvas_api.time.sleep", lambda _: None)

    with respx.mock(assert_all_called=True) as router:
        router.get("https://canvas.test/api/v1/announcements").respond(
            200,
            json=[],
        )

        with CanvasClient("https://canvas.test", "token") as client:
            announcements = client.list_announcements([100])

    assert announcements == []


def test_list_calendar_events(monkeypatch):
    monkeypatch.setattr("canvasctl.canvas_api.time.sleep", lambda _: None)

    with respx.mock(assert_all_called=True) as router:
        router.get("https://canvas.test/api/v1/calendar_events").respond(
            200,
            json=[
                {
                    "id": 50,
                    "title": "Midterm Exam",
                    "description": "<p>Chapters 1-5</p>",
                    "start_at": "2025-03-15T09:00:00Z",
                    "end_at": "2025-03-15T11:00:00Z",
                    "type": "event",
                    "context_name": "Biology 101",
                },
            ],
        )

        with CanvasClient("https://canvas.test", "token") as client:
            events = client.list_calendar_events(
                start_date="2025-03-01",
                end_date="2025-03-31",
            )

    assert len(events) == 1
    assert events[0].id == 50
    assert events[0].title == "Midterm Exam"
    assert events[0].event_type == "event"
    assert events[0].context_name == "Biology 101"


def test_list_calendar_events_with_context_codes(monkeypatch):
    monkeypatch.setattr("canvasctl.canvas_api.time.sleep", lambda _: None)

    with respx.mock(assert_all_called=True) as router:
        router.get("https://canvas.test/api/v1/calendar_events").respond(
            200,
            json=[],
        )

        with CanvasClient("https://canvas.test", "token") as client:
            events = client.list_calendar_events(
                start_date="2025-03-01",
                end_date="2025-03-31",
                context_codes=["course_100"],
            )

    assert events == []


def test_get_course_syllabus(monkeypatch):
    monkeypatch.setattr("canvasctl.canvas_api.time.sleep", lambda _: None)

    with respx.mock(assert_all_called=True) as router:
        router.get("https://canvas.test/api/v1/courses/100").respond(
            200,
            json={
                "id": 100,
                "name": "Biology 101",
                "syllabus_body": "<h1>Syllabus</h1><p>Welcome to Biology.</p>",
            },
        )

        with CanvasClient("https://canvas.test", "token") as client:
            data = client.get_course_syllabus(100)

    assert data["id"] == 100
    assert data["name"] == "Biology 101"
    assert "syllabus_body" in data
    assert "<h1>" in data["syllabus_body"]


def test_list_announcements_pagination(monkeypatch):
    monkeypatch.setattr("canvasctl.canvas_api.time.sleep", lambda _: None)

    with respx.mock(assert_all_called=True) as router:
        router.get("https://canvas.test/api/v1/announcements").respond(
            200,
            json=[
                {
                    "id": 10,
                    "title": "Page 1",
                    "message": "",
                    "context_code": "course_100",
                    "posted_at": None,
                    "author": {},
                },
            ],
            headers={
                "Link": '<https://canvas.test/api/v1/announcements-page2>; rel="next"'
            },
        )
        router.get("https://canvas.test/api/v1/announcements-page2").respond(
            200,
            json=[
                {
                    "id": 11,
                    "title": "Page 2",
                    "message": "",
                    "context_code": "course_100",
                    "posted_at": None,
                    "author": {},
                },
            ],
        )

        with CanvasClient("https://canvas.test", "token") as client:
            announcements = client.list_announcements([100])

    assert len(announcements) == 2
    assert announcements[0].id == 10
    assert announcements[1].id == 11
