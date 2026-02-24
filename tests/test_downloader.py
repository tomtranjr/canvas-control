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


def test_plan_course_download_tasks_with_course_dest(tmp_path):
    course = _course()
    files = [_file(11, "intro.pdf")]
    course_dest = tmp_path / "my-class"

    tasks = plan_course_download_tasks(
        course, files, dest_root=tmp_path, course_dest=course_dest,
    )

    assert len(tasks) == 1
    # Files should land under course_dest directly, not under course_slug
    assert tasks[0].local_path == course_dest / "Week 1" / "intro.pdf"
    # Should NOT contain the course slug in the path
    assert "math101-1" not in str(tasks[0].local_path)


def test_repeated_downloads_are_idempotent(tmp_path):
    """Simulate two consecutive download runs and verify the second skips everything."""
    from canvasctl.downloader import result_to_manifest_item
    from canvasctl.manifest import index_items_by_file_id

    course = _course()
    files = [_file(11, "intro.pdf"), _file(12, "notes.pdf")]
    tasks = plan_course_download_tasks(course, files, dest_root=tmp_path)

    # --- Run 1: fresh download ---
    client = FakeDownloadClient()
    results_run1 = download_tasks(
        client,
        tasks,
        previous_items_by_file_id=None,
        force=False,
        concurrency=4,
        console=Console(record=True),
    )

    assert all(r.status == "downloaded" for r in results_run1)

    # Build manifest from run 1 (as _download_for_courses does)
    manifest_items = [result_to_manifest_item(r) for r in results_run1]
    manifest_payload = {"items": manifest_items}
    previous_by_file_id = index_items_by_file_id(manifest_payload)

    # --- Run 2: repeat with same manifest ---
    tasks2 = plan_course_download_tasks(course, files, dest_root=tmp_path)
    client2 = FakeDownloadClient()
    results_run2 = download_tasks(
        client2,
        tasks2,
        previous_items_by_file_id=previous_by_file_id,
        force=False,
        concurrency=4,
        console=Console(record=True),
    )

    assert all(r.status == "skipped" for r in results_run2)
    assert client2.downloaded == []

    # Now simulate the fix: for skipped results, carry forward previous manifest items
    manifest_items_run2 = []
    for result in results_run2:
        if result.status == "skipped":
            prev = previous_by_file_id.get(result.task.file.file_id)
            if prev is not None:
                manifest_items_run2.append(prev)
                continue
        manifest_items_run2.append(result_to_manifest_item(result))

    # Verify carried-forward items retain "downloaded" status
    for item in manifest_items_run2:
        assert item["status"] == "downloaded"

    # --- Run 3: repeat again with run 2's manifest ---
    manifest_payload_run2 = {"items": manifest_items_run2}
    previous_by_file_id_run2 = index_items_by_file_id(manifest_payload_run2)

    tasks3 = plan_course_download_tasks(course, files, dest_root=tmp_path)
    client3 = FakeDownloadClient()
    results_run3 = download_tasks(
        client3,
        tasks3,
        previous_items_by_file_id=previous_by_file_id_run2,
        force=False,
        concurrency=4,
        console=Console(record=True),
    )

    # Run 3 should still skip everything (idempotent)
    assert all(r.status == "skipped" for r in results_run3)
    assert client3.downloaded == []


def test_skipped_without_previous_entry_uses_result(tmp_path):
    """When a file is skipped but has no previous manifest entry, use result_to_manifest_item."""
    from canvasctl.downloader import result_to_manifest_item

    course = _course()
    file_obj = _file(11, "intro.pdf")
    task = plan_course_download_tasks(course, [file_obj], dest_root=tmp_path)[0]

    # Create a skipped result with no previous entry
    from canvasctl.downloader import DownloadResult

    skipped_result = DownloadResult(
        task=task,
        status="skipped",
        bytes_downloaded=0,
        retries=0,
        error=None,
        sha256=None,
        etag=None,
    )

    # Without a previous entry, result_to_manifest_item should be used
    item = result_to_manifest_item(skipped_result)
    assert item["status"] == "skipped"


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
