from __future__ import annotations

import os

import pytest

from canvasctl.canvas_api import CanvasClient


@pytest.mark.live
def test_live_canvas_smoke(tmp_path):
    base_url = os.getenv("CANVAS_BASE_URL")
    token = os.getenv("CANVAS_TOKEN")
    course_id = os.getenv("CANVAS_TEST_COURSE_ID")

    if not base_url or not token or not course_id:
        pytest.skip("Set CANVAS_BASE_URL, CANVAS_TOKEN, and CANVAS_TEST_COURSE_ID for live tests")

    with CanvasClient(base_url, token) as client:
        courses = client.list_courses(include_all=True)
        assert isinstance(courses, list)

        files = client.list_course_files(int(course_id))
        if not files:
            pytest.skip("Selected course has no downloadable files for live smoke test")

        url = files[0].get("url") or files[0].get("download_url")
        if not isinstance(url, str) or not url:
            pytest.skip("First file did not contain a downloadable URL")

        destination = tmp_path / "live-smoke-download.bin"
        byte_count, _sha256, _etag = client.download_file(url, destination)

        assert destination.exists()
        assert byte_count > 0
