from __future__ import annotations

from pathlib import Path

from rich.console import Console

from canvasctl.canvas_api import CourseSummary, RemoteFile
from canvasctl.downloader import download_tasks, plan_course_download_tasks


class FakeDownloadClient:
    def __init__(self):
        self.downloaded: list[str] = []

    def download_file(self, url: str, destination: Path):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"abc")
        self.downloaded.append(url)
        return 3, "sha256", "etag"


def _course() -> CourseSummary:
    return CourseSummary(
        id=1,
        course_code="MATH101",
        name="Calculus",
        workflow_state="available",
        term_name="Fall",
        start_at=None,
        end_at=None,
    )


def _file(file_id: int, filename: str) -> RemoteFile:
    return RemoteFile(
        file_id=file_id,
        course_id=1,
        display_name=filename,
        filename=filename,
        folder_path="Week 1",
        size=3,
        updated_at="2025-01-01T00:00:00Z",
        download_url=f"https://example/{file_id}",
        source_type="files",
        source_ref="files:1",
    )


def test_plan_course_download_tasks_resolves_collision(tmp_path):
    course = _course()
    files = [_file(11, "intro.pdf"), _file(12, "intro.pdf")]

    tasks = plan_course_download_tasks(course, files, dest_root=tmp_path)

    paths = [task.local_path.name for task in tasks]
    assert paths[0] == "intro.pdf"
    assert paths[1] == "intro_12.pdf"


def test_download_tasks_skips_unchanged(tmp_path):
    course = _course()
    file_obj = _file(11, "intro.pdf")
    task = plan_course_download_tasks(course, [file_obj], dest_root=tmp_path)[0]

    task.local_path.parent.mkdir(parents=True, exist_ok=True)
    task.local_path.write_bytes(b"abc")

    previous_items = {
        11: {
            "status": "downloaded",
            "size": 3,
            "updated_at": "2025-01-01T00:00:00Z",
            "sha256": "sha256",
            "etag": "etag",
        }
    }

    client = FakeDownloadClient()
    results = download_tasks(
        client,
        [task],
        previous_items_by_file_id=previous_items,
        force=False,
        concurrency=4,
        console=Console(record=True),
    )

    assert results[0].status == "skipped"
    assert client.downloaded == []
