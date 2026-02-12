from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NotRequired, TypedDict


class ManifestItem(TypedDict):
    file_id: int | None
    course_id: int
    display_name: str
    source_type: str
    source_ref: str
    remote_url: str | None
    local_path: str | None
    size: int | None
    updated_at: str | None
    etag: str | None
    sha256: str | None
    status: str
    error: str | None


class CourseRunSummary(TypedDict):
    course_id: int
    course_code: str
    course_name: str
    manifest_path: str
    counts: dict[str, int]
    unresolved: int


class ManifestPayload(TypedDict):
    run_id: str
    base_url: str
    sources: list[str]
    started_at: str
    completed_at: str
    items: list[ManifestItem]
    course_id: NotRequired[int]
    courses: NotRequired[list[CourseRunSummary]]


def course_manifest_path(dest_root: Path, course_slug: str) -> Path:
    return dest_root / course_slug / ".canvasctl-manifest.json"


def load_manifest(path: Path) -> ManifestPayload | dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def index_items_by_file_id(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for item in payload.get("items", []):
        file_id = item.get("file_id")
        if isinstance(file_id, int):
            out[file_id] = item
    return out


def write_manifest(path: Path, payload: ManifestPayload | dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_course_manifest(dest_root: Path, course_slug: str, payload: ManifestPayload | dict[str, Any]) -> Path:
    path = course_manifest_path(dest_root, course_slug)
    write_manifest(path, payload)
    return path


def write_run_summary(dest_root: Path, payload: ManifestPayload | dict[str, Any]) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = dest_root / ".canvasctl-runs" / f"{timestamp}.json"
    write_manifest(path, payload)
    return path
