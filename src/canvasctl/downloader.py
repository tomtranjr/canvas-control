from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

from canvasctl.canvas_api import CanvasClient, CourseSummary, RemoteFile
from canvasctl.manifest import ManifestItem

_INVALID_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._ -]+")


@dataclass(slots=True)
class DownloadTask:
    course_id: int
    course_slug: str
    file: RemoteFile
    local_path: Path


@dataclass(slots=True)
class DownloadResult:
    task: DownloadTask
    status: str
    bytes_downloaded: int
    retries: int
    error: str | None
    sha256: str | None
    etag: str | None


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    lowered = _INVALID_SEGMENT_RE.sub("-", lowered)
    lowered = lowered.replace(" ", "-")
    lowered = re.sub(r"-+", "-", lowered)
    lowered = lowered.strip("-._")
    return lowered or "course"


def sanitize_segment(segment: str) -> str:
    cleaned = segment.replace("\\", "/").strip()
    cleaned = _INVALID_SEGMENT_RE.sub("_", cleaned)
    cleaned = cleaned.strip(" .")
    if cleaned in {"", ".", ".."}:
        return "_"
    return cleaned


def sanitize_folder_path(folder_path: str) -> Path:
    if not folder_path:
        return Path()
    parts: list[str] = []
    for part in folder_path.replace("\\", "/").split("/"):
        clean = sanitize_segment(part)
        if clean and clean not in {".", ".."}:
            parts.append(clean)
    return Path(*parts) if parts else Path()


def build_course_slug(course: CourseSummary) -> str:
    label = course.course_code or course.name or f"course-{course.id}"
    return f"{slugify(label)}-{course.id}"


def _safe_filename(remote_file: RemoteFile) -> str:
    raw = remote_file.filename or remote_file.display_name or f"file-{remote_file.file_id}"
    if "." in raw:
        stem, extension = raw.rsplit(".", 1)
        stem = sanitize_segment(stem)
        extension = sanitize_segment(extension)
        if extension:
            return f"{stem}.{extension}"
        return stem
    return sanitize_segment(raw)


def plan_course_download_tasks(
    course: CourseSummary,
    remote_files: list[RemoteFile],
    *,
    dest_root: Path,
) -> list[DownloadTask]:
    course_slug = build_course_slug(course)
    course_root = dest_root / course_slug

    planned: dict[Path, int] = {}
    tasks: list[DownloadTask] = []

    for remote_file in remote_files:
        folder_path = sanitize_folder_path(remote_file.folder_path)
        filename = _safe_filename(remote_file)
        candidate = course_root / folder_path / filename

        if candidate in planned and planned[candidate] != remote_file.file_id:
            stem = candidate.stem
            suffix = candidate.suffix
            candidate = candidate.with_name(f"{stem}_{remote_file.file_id}{suffix}")

        planned[candidate] = remote_file.file_id
        tasks.append(
            DownloadTask(
                course_id=course.id,
                course_slug=course_slug,
                file=remote_file,
                local_path=candidate,
            )
        )

    return tasks


def _is_unchanged(task: DownloadTask, previous_item: dict[str, Any] | None) -> bool:
    if previous_item is None:
        return False
    if previous_item.get("status") != "downloaded":
        return False
    if not task.local_path.exists():
        return False

    previous_size = previous_item.get("size")
    previous_updated_at = previous_item.get("updated_at")

    if task.file.size is not None and previous_size != task.file.size:
        return False

    if task.file.updated_at and previous_updated_at:
        if previous_updated_at != task.file.updated_at:
            return False

    return True


def _download_one(client: CanvasClient, task: DownloadTask) -> DownloadResult:
    try:
        bytes_downloaded, sha256, etag = client.download_file(task.file.download_url, task.local_path)
        return DownloadResult(
            task=task,
            status="downloaded",
            bytes_downloaded=bytes_downloaded,
            retries=0,
            error=None,
            sha256=sha256,
            etag=etag,
        )
    except Exception as exc:  # noqa: BLE001
        return DownloadResult(
            task=task,
            status="failed",
            bytes_downloaded=0,
            retries=0,
            error=str(exc),
            sha256=None,
            etag=None,
        )


def download_tasks(
    client: CanvasClient,
    tasks: list[DownloadTask],
    *,
    previous_items_by_file_id: dict[int, dict[str, Any]] | None,
    force: bool,
    concurrency: int,
    console: Console,
) -> list[DownloadResult]:
    previous_items = previous_items_by_file_id or {}

    scheduled: list[DownloadTask] = []
    results: list[DownloadResult] = []

    for task in tasks:
        previous_item = previous_items.get(task.file.file_id)
        if not force and _is_unchanged(task, previous_item):
            results.append(
                DownloadResult(
                    task=task,
                    status="skipped",
                    bytes_downloaded=0,
                    retries=0,
                    error=None,
                    sha256=previous_item.get("sha256") if previous_item else None,
                    etag=previous_item.get("etag") if previous_item else None,
                )
            )
            continue
        scheduled.append(task)

    if scheduled:
        max_workers = max(1, concurrency)
        progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            console=console,
        )

        with progress:
            progress_task_id = progress.add_task(
                "Downloading files",
                total=len(scheduled),
            )
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {
                    executor.submit(_download_one, client, task): task for task in scheduled
                }
                for future in as_completed(future_map):
                    result = future.result()
                    results.append(result)
                    progress.advance(progress_task_id)

    results.sort(key=lambda result: (result.task.course_id, result.task.file.file_id, result.status))
    return results


def result_to_manifest_item(result: DownloadResult) -> ManifestItem:
    return {
        "file_id": result.task.file.file_id,
        "course_id": result.task.course_id,
        "display_name": result.task.file.display_name,
        "source_type": result.task.file.source_type,
        "source_ref": result.task.file.source_ref,
        "remote_url": result.task.file.download_url,
        "local_path": str(result.task.local_path.resolve()),
        "size": result.task.file.size,
        "updated_at": result.task.file.updated_at,
        "etag": result.etag,
        "sha256": result.sha256,
        "status": result.status,
        "error": result.error,
    }


def summarize_results(results: list[DownloadResult]) -> dict[str, int]:
    counts = {"downloaded": 0, "skipped": 0, "failed": 0}
    for result in results:
        if result.status in counts:
            counts[result.status] += 1
    return counts
