from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def course_manifest_path(dest_root: Path, course_slug: str) -> Path:
    return dest_root / course_slug / ".canvasctl-manifest.json"


def load_manifest(path: Path) -> dict[str, Any]:
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


def write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_course_manifest(dest_root: Path, course_slug: str, payload: dict[str, Any]) -> Path:
    path = course_manifest_path(dest_root, course_slug)
    write_manifest(path, payload)
    return path


def write_run_summary(dest_root: Path, payload: dict[str, Any]) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = dest_root / ".canvasctl-runs" / f"{timestamp}.json"
    write_manifest(path, payload)
    return path
