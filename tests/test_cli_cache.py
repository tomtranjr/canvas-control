"""Tests for the cvsctl cache subcommands."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from canvasctl.canvas_api import CourseSummary
from canvasctl.cli import app
from canvasctl.config import AppConfig
from canvasctl.course_cache import write_cache

runner = CliRunner()

SAMPLE_COURSES = [
    CourseSummary(
        id=100,
        course_code="ML501",
        name="Advanced Machine Learning",
        workflow_state="available",
        term_name="Spring 2026",
        start_at=None,
        end_at=None,
    ),
    CourseSummary(
        id=200,
        course_code="CS101",
        name="Intro to Computer Science",
        workflow_state="available",
        term_name="Spring 2026",
        start_at=None,
        end_at=None,
    ),
]


def test_cache_refresh_requires_base_url(monkeypatch):
    """cache refresh fails if no base_url is configured."""
    monkeypatch.setattr(
        "canvasctl.cli._load_config_or_fail",
        lambda: AppConfig(base_url=None),
    )
    result = runner.invoke(app, ["cache", "refresh"])
    assert result.exit_code != 0
    assert "base_url" in result.stdout.lower() or "url" in result.stdout.lower()


def test_cache_refresh_fetches_and_writes(tmp_path, monkeypatch):
    """cache refresh fetches courses and writes to cache."""
    monkeypatch.setattr("canvasctl.course_cache.cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "canvasctl.cli._load_config_or_fail",
        lambda: AppConfig(base_url="https://canvas.test"),
    )
    monkeypatch.setattr(
        "canvasctl.cli._resolve_base_url_or_fail",
        lambda cfg, url: "https://canvas.test",
    )

    class FakeClient:
        def list_courses(self, *, include_all):
            return SAMPLE_COURSES

    def fake_run(url, action):
        return action(FakeClient())

    monkeypatch.setattr("canvasctl.cli._run_with_client", fake_run)

    result = runner.invoke(app, ["cache", "refresh"])
    assert result.exit_code == 0
    assert "Cached 2 course(s)" in result.stdout
    # Check for course codes in the table output (which may be wrapped)
    assert "ML501" in result.stdout
    assert "CS101" in result.stdout
    assert (tmp_path / "courses.json").exists()


def test_cache_show_no_cache(tmp_path, monkeypatch):
    """cache show prints message when no cache exists."""
    monkeypatch.setattr("canvasctl.course_cache.cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "canvasctl.cli._load_config_or_fail",
        lambda: AppConfig(base_url="https://canvas.test"),
    )
    monkeypatch.setattr(
        "canvasctl.cli._resolve_base_url_or_fail",
        lambda cfg, url: "https://canvas.test",
    )

    result = runner.invoke(app, ["cache", "show"])
    assert result.exit_code == 0
    assert "No course cache found" in result.stdout


def test_cache_show_with_cache(tmp_path, monkeypatch):
    """cache show prints cache info and courses."""
    monkeypatch.setattr("canvasctl.course_cache.cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "canvasctl.cli._load_config_or_fail",
        lambda: AppConfig(base_url="https://canvas.test"),
    )
    monkeypatch.setattr(
        "canvasctl.cli._resolve_base_url_or_fail",
        lambda cfg, url: "https://canvas.test",
    )

    # Pre-populate the cache
    write_cache("https://canvas.test", SAMPLE_COURSES)

    result = runner.invoke(app, ["cache", "show"])
    assert result.exit_code == 0
    assert "Course Cache Info" in result.stdout
    # Check for course codes in the table output (which may be wrapped)
    assert "ML501" in result.stdout
    assert "CS101" in result.stdout
    assert "courses" in result.stdout.lower()


def test_cache_show_json_output(tmp_path, monkeypatch):
    """cache show --json returns raw JSON."""
    monkeypatch.setattr("canvasctl.course_cache.cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "canvasctl.cli._load_config_or_fail",
        lambda: AppConfig(base_url="https://canvas.test"),
    )
    monkeypatch.setattr(
        "canvasctl.cli._resolve_base_url_or_fail",
        lambda cfg, url: "https://canvas.test",
    )

    # Pre-populate the cache
    write_cache("https://canvas.test", SAMPLE_COURSES)

    result = runner.invoke(app, ["cache", "show", "--json"])
    assert result.exit_code == 0
    assert '"schema_version"' in result.stdout
    assert '"base_url"' in result.stdout
    assert '"courses"' in result.stdout
    assert "ML501" in result.stdout
