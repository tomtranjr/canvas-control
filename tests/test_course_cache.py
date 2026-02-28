from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from canvasctl.canvas_api import CourseSummary
from canvasctl.course_cache import (
    cache_info,
    courses_from_cache,
    get_cached_courses,
    is_cache_valid,
    load_cache,
    write_cache,
)

SAMPLE_COURSES = [
    CourseSummary(
        id=100,
        course_code="ML501",
        name="Advanced Machine Learning",
        workflow_state="available",
        term_name="Spring 2026",
        start_at=None,
        end_at=None,
    )
]


def test_write_and_load_roundtrip(tmp_path, monkeypatch):
    """Test writing and loading cache roundtrip."""
    monkeypatch.setattr("canvasctl.course_cache.cache_dir", lambda: tmp_path)
    path = write_cache("https://canvas.test", SAMPLE_COURSES)
    assert path.exists()
    loaded = load_cache("https://canvas.test")
    assert loaded["base_url"] == "https://canvas.test"
    assert len(loaded["courses"]) == 1
    assert loaded["courses"][0]["id"] == 100


def test_load_cache_missing_returns_empty(tmp_path, monkeypatch):
    """Test loading missing cache returns empty dict."""
    monkeypatch.setattr("canvasctl.course_cache.cache_dir", lambda: tmp_path)
    result = load_cache("https://canvas.test")
    assert result == {}


def test_load_cache_wrong_base_url_returns_empty(tmp_path, monkeypatch):
    """Test loading cache with wrong base_url returns empty dict."""
    monkeypatch.setattr("canvasctl.course_cache.cache_dir", lambda: tmp_path)
    write_cache("https://canvas.test", SAMPLE_COURSES)
    result = load_cache("https://different.instructure.com")
    assert result == {}


def test_load_cache_malformed_json_returns_empty(tmp_path, monkeypatch):
    """Test loading malformed JSON returns empty dict."""
    monkeypatch.setattr("canvasctl.course_cache.cache_dir", lambda: tmp_path)
    (tmp_path / "courses.json").write_text("not json", encoding="utf-8")
    result = load_cache("https://canvas.test")
    assert result == {}


def test_is_cache_valid_no_ttl_always_valid():
    """Test cache with no TTL is always valid."""
    cached = {"ttl_seconds": None, "fetched_at": "2020-01-01T00:00:00+00:00", "courses": []}
    assert is_cache_valid(cached) is True


def test_is_cache_valid_expired():
    """Test cache with expired TTL is invalid."""
    old_time = (datetime.now(UTC) - timedelta(seconds=3601)).isoformat()
    cached = {"ttl_seconds": 3600, "fetched_at": old_time, "courses": []}
    assert is_cache_valid(cached) is False


def test_is_cache_valid_not_yet_expired():
    """Test cache with unexpired TTL is valid."""
    recent = (datetime.now(UTC) - timedelta(seconds=100)).isoformat()
    cached = {"ttl_seconds": 3600, "fetched_at": recent, "courses": []}
    assert is_cache_valid(cached) is True


def test_is_cache_valid_empty_dict():
    """Test empty dict is invalid."""
    assert is_cache_valid({}) is False


def test_courses_from_cache_roundtrip(tmp_path, monkeypatch):
    """Test deserializing courses from cache."""
    monkeypatch.setattr("canvasctl.course_cache.cache_dir", lambda: tmp_path)
    write_cache("https://canvas.test", SAMPLE_COURSES)
    cached = load_cache("https://canvas.test")
    courses = courses_from_cache(cached)
    assert len(courses) == 1
    assert courses[0].id == 100
    assert courses[0].name == "Advanced Machine Learning"


def test_get_cached_courses_hit(tmp_path, monkeypatch):
    """Test get_cached_courses returns list on cache hit."""
    monkeypatch.setattr("canvasctl.course_cache.cache_dir", lambda: tmp_path)
    write_cache("https://canvas.test", SAMPLE_COURSES)
    result = get_cached_courses("https://canvas.test")
    assert result is not None
    assert result[0].id == 100


def test_get_cached_courses_miss_returns_none(tmp_path, monkeypatch):
    """Test get_cached_courses returns None on cache miss."""
    monkeypatch.setattr("canvasctl.course_cache.cache_dir", lambda: tmp_path)
    result = get_cached_courses("https://canvas.test")
    assert result is None


def test_cache_info_absent(tmp_path, monkeypatch):
    """Test cache_info returns absent state."""
    monkeypatch.setattr("canvasctl.course_cache.cache_dir", lambda: tmp_path)
    info = cache_info("https://canvas.test")
    assert info["present"] is False


def test_cache_info_present(tmp_path, monkeypatch):
    """Test cache_info returns present state with metadata."""
    monkeypatch.setattr("canvasctl.course_cache.cache_dir", lambda: tmp_path)
    write_cache("https://canvas.test", SAMPLE_COURSES)
    info = cache_info("https://canvas.test")
    assert info["present"] is True
    assert info["course_count"] == 1
    assert info["valid"] is True
