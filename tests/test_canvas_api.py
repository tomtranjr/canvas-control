from __future__ import annotations

import httpx
import pytest
import respx

from canvasctl.canvas_api import CanvasClient


def test_get_paginated_follows_next_link(monkeypatch):
    monkeypatch.setattr("canvasctl.canvas_api.time.sleep", lambda _: None)

    with respx.mock(assert_all_called=True) as router:
        router.get("https://canvas.test/api/v1/courses").respond(
            200,
            json=[{"id": 1}],
            headers={
                "Link": '<https://canvas.test/api/v1/courses-page-2>; rel="next"'
            },
        )
        router.get("https://canvas.test/api/v1/courses-page-2").respond(
            200,
            json=[{"id": 2}],
        )

        with CanvasClient("https://canvas.test", "token") as client:
            payload = client.get_paginated("/courses")

    assert payload == [{"id": 1}, {"id": 2}]


def test_retry_on_429(monkeypatch):
    monkeypatch.setattr("canvasctl.canvas_api.time.sleep", lambda _: None)

    call_count = {"value": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        call_count["value"] += 1
        if call_count["value"] == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json=[])

    with respx.mock(assert_all_called=True) as router:
        router.get("https://canvas.test/api/v1/courses/1/files").mock(side_effect=handler)

        with CanvasClient("https://canvas.test", "token") as client:
            payload = client.list_course_files(1)

    assert payload == []
    assert call_count["value"] == 2


def test_list_courses_with_grades_parses_enrollments(monkeypatch):
    monkeypatch.setattr("canvasctl.canvas_api.time.sleep", lambda _: None)

    with respx.mock(assert_all_called=True) as router:
        router.get("https://canvas.test/api/v1/courses").respond(
            200,
            json=[
                {
                    "id": 100,
                    "course_code": "BIO101",
                    "name": "Biology",
                    "enrollments": [
                        {
                            "type": "student",
                            "computed_current_score": 92.5,
                            "computed_current_grade": "A-",
                        }
                    ],
                },
                {
                    "id": 200,
                    "course_code": "MATH201",
                    "name": "Calculus",
                    "enrollments": [],
                },
            ],
        )

        with CanvasClient("https://canvas.test", "token") as client:
            grades = client.list_courses_with_grades(include_all=False)

    assert len(grades) == 2
    assert grades[0].course_id == 100
    assert grades[0].course_code == "BIO101"
    assert grades[0].current_score == 92.5
    assert grades[0].current_grade == "A-"
    assert grades[1].course_id == 200
    assert grades[1].current_score is None
    assert grades[1].current_grade is None


def test_list_assignment_grades_parses_submissions(monkeypatch):
    monkeypatch.setattr("canvasctl.canvas_api.time.sleep", lambda _: None)

    with respx.mock(assert_all_called=True) as router:
        router.get("https://canvas.test/api/v1/courses/100/assignments").respond(
            200,
            json=[
                {
                    "id": 10,
                    "name": "Homework 1",
                    "points_possible": 100.0,
                    "submission": {
                        "score": 95.0,
                        "grade": "A",
                        "submitted_at": "2025-01-15T10:00:00Z",
                        "workflow_state": "graded",
                    },
                },
                {
                    "id": 11,
                    "name": "Quiz 1",
                    "points_possible": 50.0,
                    "submission": None,
                },
            ],
        )

        with CanvasClient("https://canvas.test", "token") as client:
            grades = client.list_assignment_grades(100)

    assert len(grades) == 2
    assert grades[0].assignment_id == 10
    assert grades[0].score == 95.0
    assert grades[0].grade == "A"
    assert grades[0].workflow_state == "graded"
    assert grades[1].assignment_id == 11
    assert grades[1].score is None
    assert grades[1].grade is None


def test_get_paginated_detects_loop(monkeypatch):
    monkeypatch.setattr("canvasctl.canvas_api.time.sleep", lambda _: None)

    with respx.mock(assert_all_called=True) as router:
        router.get("https://canvas.test/api/v1/courses").respond(
            200,
            json=[{"id": 1}],
            headers={
                "Link": '<https://canvas.test/api/v1/courses>; rel="next"'
            },
        )

        with CanvasClient("https://canvas.test", "token") as client:
            with pytest.raises(RuntimeError, match="Pagination loop detected"):
                client.get_paginated("/courses")
