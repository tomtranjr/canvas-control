from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from canvasctl.canvas_api import CourseSummary
from canvasctl.cli import app
from canvasctl.config import AppConfig


class FakeClient:
    def __init__(self):
        self.submissions: list[tuple[int, int, str, dict[str, object]]] = []

    def list_courses(self, *, include_all: bool):
        assert include_all is True
        return [
            CourseSummary(
                id=100,
                course_code="BIO101",
                name="Biology",
                workflow_state="available",
                term_name="Spring 2026",
                start_at=None,
                end_at=None,
            )
        ]

    def list_assignments(self, course_id: int):
        assert course_id == 100
        return [
            {
                "id": 10,
                "name": "Homework 1",
                "submission_types": ["online_upload", "online_text_entry", "online_url"],
                "html_url": "https://canvas.test/courses/100/assignments/10",
            }
        ]

    def init_assignment_file_upload(
        self,
        course_id: int,
        assignment_id: int,
        *,
        filename: str,
        size: int,
    ):
        assert course_id == 100
        assert assignment_id == 10
        assert filename
        assert size > 0
        return {
            "upload_url": "https://upload.canvas.test",
            "upload_params": {"token": "abc"},
        }

    def upload_file_to_canvas(self, upload_url: str, upload_params: dict[str, object], local_path: Path):
        assert upload_url == "https://upload.canvas.test"
        assert upload_params == {"token": "abc"}
        assert local_path.is_file()
        return {"id": 7001}

    def submit_assignment(
        self,
        course_id: int,
        assignment_id: int,
        *,
        submission_type: str,
        body: dict[str, object],
    ):
        self.submissions.append((course_id, assignment_id, submission_type, body))
        return {"id": 9001, "workflow_state": "submitted"}


def _patch_common(monkeypatch, client):
    monkeypatch.setattr(
        "canvasctl.cli._load_config_or_fail",
        lambda: AppConfig(base_url="https://canvas.test"),
    )
    monkeypatch.setattr(
        "canvasctl.cli._resolve_base_url_or_fail",
        lambda _cfg, _override: "https://canvas.test",
    )
    monkeypatch.setattr(
        "canvasctl.cli._run_with_client",
        lambda _base_url, action: action(client),
    )


def test_assignments_submit_file_success(monkeypatch, tmp_path):
    runner = CliRunner()
    client = FakeClient()
    _patch_common(monkeypatch, client)

    local_file = tmp_path / "hw.py"
    local_file.write_text("print('ok')\n", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "assignments",
            "submit",
            "--course",
            "100",
            "--assignment",
            "10",
            "--file",
            str(local_file),
        ],
    )

    assert result.exit_code == 0
    assert "submitted_online_upload" in result.output
    assert client.submissions[0][2] == "online_upload"
    assert client.submissions[0][3] == {"file_ids": [7001]}


def test_assignments_submit_text_json(monkeypatch):
    runner = CliRunner()
    client = FakeClient()
    _patch_common(monkeypatch, client)

    result = runner.invoke(
        app,
        [
            "assignments",
            "submit",
            "--course",
            "100",
            "--assignment",
            "Homework 1",
            "--text",
            "done",
            "--json",
        ],
    )

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["action_taken"] == "submitted_online_text_entry"
    assert client.submissions[0][2] == "online_text_entry"
    assert client.submissions[0][3] == {"body": "done"}


def test_assignments_submit_url(monkeypatch):
    runner = CliRunner()
    client = FakeClient()
    _patch_common(monkeypatch, client)

    result = runner.invoke(
        app,
        [
            "assignments",
            "submit",
            "--course",
            "BIO101",
            "--assignment",
            "Homework 1",
            "--url",
            "https://example.com/work",
        ],
    )

    assert result.exit_code == 0
    assert client.submissions[0][2] == "online_url"
    assert client.submissions[0][3] == {"url": "https://example.com/work"}


def test_assignments_submit_ambiguous_assignment(monkeypatch):
    runner = CliRunner()
    client = FakeClient()
    _patch_common(monkeypatch, client)
    client.list_assignments = lambda _course_id: [  # type: ignore[method-assign]
        {"id": 10, "name": "Homework", "submission_types": ["online_text_entry"], "html_url": "u1"},
        {"id": 20, "name": "Homework", "submission_types": ["online_text_entry"], "html_url": "u2"},
    ]

    result = runner.invoke(
        app,
        [
            "assignments",
            "submit",
            "--course",
            "100",
            "--assignment",
            "Homework",
            "--text",
            "done",
        ],
    )

    assert result.exit_code == 1
    assert "Ambiguous assignment selector" in result.output


def test_assignments_submit_rejects_missing_file(monkeypatch):
    runner = CliRunner()
    client = FakeClient()
    _patch_common(monkeypatch, client)

    result = runner.invoke(
        app,
        [
            "assignments",
            "submit",
            "--course",
            "100",
            "--assignment",
            "10",
            "--file",
            "/tmp/does-not-exist-12345.py",
        ],
    )

    assert result.exit_code == 1
    assert "does not exist" in result.output
