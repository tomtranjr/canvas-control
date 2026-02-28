from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import platformdirs

from canvasctl.canvas_api import CourseSummary

CACHE_SCHEMA_VERSION = 1
_APP_CACHE_NAME = "canvas-control"


def cache_dir() -> Path:
    """Return the cache directory for canvas-control."""
    return Path(platformdirs.user_cache_dir(_APP_CACHE_NAME))


def cache_path() -> Path:
    """Return the full path to the courses cache file."""
    return cache_dir() / "courses.json"


def _url_key(base_url: str) -> str:
    """Normalize base_url for use as a cache key."""
    return base_url.rstrip("/").lower()


def load_cache(base_url: str) -> dict[str, Any]:
    """Load the raw cache payload for the given base_url.

    Returns {} if the file is missing, malformed, or belongs to a different
    base_url. Never raises.
    """
    path = cache_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    if _url_key(raw.get("base_url", "")) != _url_key(base_url):
        return {}
    return raw


def write_cache(base_url: str, courses: list[CourseSummary], *, ttl_seconds: int | None = None) -> Path:
    """Persist the course list to disk under the given base_url key.

    Creates the cache directory if needed. Returns the path written.
    """
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "base_url": base_url.rstrip("/"),
        "fetched_at": datetime.now(UTC).isoformat(),
        "ttl_seconds": ttl_seconds,
        "courses": [asdict(c) for c in courses],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def is_cache_valid(cached: dict[str, Any]) -> bool:
    """Return True if the cache exists and is not expired.

    With ttl_seconds=None (the default), the cache is always valid if it exists.
    """
    if not cached:
        return False
    ttl = cached.get("ttl_seconds")
    if ttl is None:
        return True  # Never expires
    fetched_at_str = cached.get("fetched_at", "")
    if not fetched_at_str:
        return False
    try:
        fetched_at = datetime.fromisoformat(fetched_at_str)
        age_seconds = (datetime.now(UTC) - fetched_at).total_seconds()
        return age_seconds < ttl
    except (ValueError, TypeError):
        return False


def courses_from_cache(cached: dict[str, Any]) -> list[CourseSummary]:
    """Deserialize CourseSummary objects from a raw cache payload."""
    raw_courses = cached.get("courses", [])
    courses: list[CourseSummary] = []
    for item in raw_courses:
        if not isinstance(item, dict):
            continue
        try:
            courses.append(CourseSummary(
                id=int(item["id"]),
                course_code=item.get("course_code") or None,
                name=item.get("name") or "",
                workflow_state=item.get("workflow_state"),
                term_name=item.get("term_name"),
                start_at=item.get("start_at"),
                end_at=item.get("end_at"),
            ))
        except (KeyError, ValueError, TypeError):
            continue
    return courses


def get_cached_courses(base_url: str) -> list[CourseSummary] | None:
    """Return cached courses if cache is valid, else None.

    This is the primary public entry point for consumers that want to try
    the cache before falling back to the Canvas API.
    """
    cached = load_cache(base_url)
    if not is_cache_valid(cached):
        return None
    return courses_from_cache(cached)


def cache_info(base_url: str) -> dict[str, Any]:
    """Return cache metadata dict suitable for display."""
    cached = load_cache(base_url)
    if not cached:
        return {"present": False, "base_url": base_url}
    return {
        "present": True,
        "base_url": cached.get("base_url"),
        "fetched_at": cached.get("fetched_at"),
        "ttl_seconds": cached.get("ttl_seconds"),
        "course_count": len(cached.get("courses", [])),
        "valid": is_cache_valid(cached),
        "path": str(cache_path()),
    }
