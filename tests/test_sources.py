from __future__ import annotations

from typing import Any

from canvasctl.canvas_api import CanvasApiError
from canvasctl.sources import collect_remote_files_for_course, extract_file_ids_from_payload, extract_file_ids_from_text


class FakeCanvasClient:
    def __init__(self):
        self.file_lookup_called: list[int] = []

    def list_course_folders(self, course_id: int) -> dict[int, str]:
        return {10: "Week 1"}

    def list_course_files(self, course_id: int) -> list[dict[str, Any]]:
        return [
            {
                "id": 11,
                "filename": "intro.pdf",
                "display_name": "Intro.pdf",
                "folder_id": 10,
                "size": 42,
                "updated_at": "2025-01-01T00:00:00Z",
                "url": "https://files.example/11",
            }
        ]

    def list_assignments(self, course_id: int) -> list[dict[str, Any]]:
        return [
            {
                "id": 100,
                "description": '<a href="https://school/files/22/download">ref</a>',
            }
        ]

    def list_discussions(self, course_id: int) -> list[dict[str, Any]]:
        return []

    def list_pages(self, course_id: int) -> list[dict[str, Any]]:
        return []

    def list_modules(self, course_id: int) -> list[dict[str, Any]]:
        return []

    def get_file(self, file_id: int) -> dict[str, Any]:
        self.file_lookup_called.append(file_id)
        return {
            "id": file_id,
            "filename": "attachment.docx",
            "display_name": "attachment.docx",
            "folder_id": 10,
            "size": 20,
            "modified_at": "2025-01-02T00:00:00Z",
            "url": f"https://files.example/{file_id}",
        }


def test_extract_file_ids_from_text():
    text = "Links /files/123/download and https://x/api/v1/files/456"
    assert extract_file_ids_from_text(text) == {123, 456}


def test_extract_file_ids_from_payload_with_attachments():
    payload = {
        "attachments": [{"id": 9}, {"id": "10"}],
        "description": "See /files/20/download",
    }
    assert extract_file_ids_from_payload(payload) == {9, 10, 20}


def test_collect_remote_files_combines_sources():
    client = FakeCanvasClient()

    files, warnings = collect_remote_files_for_course(
        client,
        course_id=1,
        sources=["files", "assignments"],
    )

    ids = {item.file_id for item in files}
    assert ids == {11, 22}
    assert client.file_lookup_called == [22]
    assert warnings == []


class RestrictedCanvasClient(FakeCanvasClient):
    def list_course_files(self, course_id: int) -> list[dict[str, Any]]:
        raise CanvasApiError("Canvas request failed (403) for courses/1/files")

    def list_pages(self, course_id: int) -> list[dict[str, Any]]:
        raise CanvasApiError("Canvas request failed (404) for courses/1/pages")

    def list_modules(self, course_id: int) -> list[dict[str, Any]]:
        return [
            {
                "id": 501,
                "items": [
                    {
                        "id": 601,
                        "title": "Module file",
                        "html_url": "https://school.instructure.com/files/33/download",
                    }
                ],
            }
        ]


def test_collect_remote_files_falls_back_to_modules_when_files_blocked():
    client = RestrictedCanvasClient()

    files, warnings = collect_remote_files_for_course(
        client,
        course_id=1,
        sources=["files", "pages", "modules"],
    )

    ids = {item.file_id for item in files}
    assert ids == {33}
    assert client.file_lookup_called == [33]
    warning_messages = [warning.detail for warning in warnings]
    assert any("Skipping files source" in message for message in warning_messages)
    assert any("Skipping pages source" in message for message in warning_messages)
