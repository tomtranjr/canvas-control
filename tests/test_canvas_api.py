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
