from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from canvasctl.canvas_api import CanvasApiError, CanvasClient, RemoteFile
from canvasctl.manifest import ManifestItem

ALL_SOURCES = ("files", "assignments", "discussions", "pages", "modules")
_FILE_ID_PATTERNS = (
    re.compile(r"/files/(\d+)(?:/download)?"),
    re.compile(r"/api/v1/files/(\d+)"),
)


@dataclass(slots=True)
class SourceWarning:
    source_type: str
    source_ref: str
    detail: str


def normalize_sources(selected: Iterable[str] | None) -> list[str]:
    if not selected:
        return list(ALL_SOURCES)
    normalized: list[str] = []
    for source in selected:
        if source not in ALL_SOURCES:
            raise ValueError(f"Unsupported source type: {source}")
        if source not in normalized:
            normalized.append(source)
    return normalized


def extract_file_ids_from_text(text: str) -> set[int]:
    found: set[int] = set()
    for pattern in _FILE_ID_PATTERNS:
        for match in pattern.findall(text):
            try:
                found.add(int(match))
            except ValueError:
                continue
    return found


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _iter_strings(payload: Any) -> Iterable[str]:
    if isinstance(payload, str):
        yield payload
        return
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_strings(item)
        return
    if isinstance(payload, dict):
        for value in payload.values():
            yield from _iter_strings(value)


def extract_file_ids_from_payload(payload: Any) -> set[int]:
    file_ids: set[int] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "attachments" in node and isinstance(node["attachments"], list):
                for attachment in node["attachments"]:
                    if isinstance(attachment, dict):
                        maybe_id = _coerce_int(attachment.get("id"))
                        if maybe_id is not None:
                            file_ids.add(maybe_id)
            for key, value in node.items():
                if key in {"file_id", "attachment_id", "content_id"}:
                    maybe_id = _coerce_int(value)
                    if maybe_id is not None:
                        file_ids.add(maybe_id)
                if isinstance(value, str):
                    file_ids.update(extract_file_ids_from_text(value))
                else:
                    walk(value)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if isinstance(node, str):
            file_ids.update(extract_file_ids_from_text(node))

    walk(payload)
    return file_ids


def _has_unresolved_file_link(payload: Any) -> bool:
    for text in _iter_strings(payload):
        lowered = text.lower()
        if "/files/" in lowered and not extract_file_ids_from_text(text):
            return True
    return False


def _source_ref(source_type: str, item: dict[str, Any]) -> str:
    item_id = item.get("id") or item.get("_id") or item.get("url") or "unknown"
    return f"{source_type}:{item_id}"


def _remote_file_from_payload(
    payload: dict[str, Any],
    *,
    course_id: int,
    folder_map: dict[int, str],
    source_type: str,
    source_ref: str,
) -> RemoteFile:
    file_id_raw = payload.get("id")
    if file_id_raw is None:
        raise CanvasApiError(f"File payload missing id for source {source_type}/{source_ref}")

    file_id = int(file_id_raw)
    filename = str(payload.get("filename") or payload.get("display_name") or f"file-{file_id}")
    display_name = str(payload.get("display_name") or filename)

    folder_id = _coerce_int(payload.get("folder_id"))
    folder_path = folder_map.get(folder_id, "") if folder_id is not None else ""

    size = _coerce_int(payload.get("size"))
    updated_at = payload.get("modified_at") or payload.get("updated_at")
    download_url = payload.get("url") or payload.get("download_url")
    if not isinstance(download_url, str) or not download_url.strip():
        raise CanvasApiError(f"File {file_id} has no downloadable URL")

    return RemoteFile(
        file_id=file_id,
        course_id=course_id,
        display_name=display_name,
        filename=filename,
        folder_path=folder_path,
        size=size,
        updated_at=updated_at,
        download_url=download_url,
        source_type=source_type,
        source_ref=source_ref,
    )


def _collect_source_items(client: CanvasClient, course_id: int, source_type: str) -> list[dict[str, Any]]:
    if source_type == "assignments":
        return client.list_assignments(course_id)
    if source_type == "discussions":
        return client.list_discussions(course_id)
    if source_type == "pages":
        return client.list_pages(course_id)
    if source_type == "modules":
        return client.list_modules(course_id)
    raise ValueError(f"Unsupported source type: {source_type}")


def collect_remote_files_for_course(
    client: CanvasClient,
    course_id: int,
    sources: Iterable[str],
) -> tuple[list[RemoteFile], list[SourceWarning]]:
    normalized_sources = normalize_sources(sources)
    warnings: list[SourceWarning] = []
    try:
        folder_map = client.list_course_folders(course_id)
    except CanvasApiError as exc:
        folder_map = {}
        warnings.append(
            SourceWarning(
                source_type="files",
                source_ref=f"files:course:{course_id}",
                detail=f"Could not list course folders: {exc}",
            )
        )

    file_map: dict[int, RemoteFile] = {}

    if "files" in normalized_sources:
        try:
            file_payloads = client.list_course_files(course_id)
        except CanvasApiError as exc:
            warnings.append(
                SourceWarning(
                    source_type="files",
                    source_ref=f"files:course:{course_id}",
                    detail=f"Skipping files source: {exc}",
                )
            )
            file_payloads = []

        for payload in file_payloads:
            source_ref = _source_ref("files", payload)
            try:
                remote = _remote_file_from_payload(
                    payload,
                    course_id=course_id,
                    folder_map=folder_map,
                    source_type="files",
                    source_ref=source_ref,
                )
            except CanvasApiError as exc:
                warnings.append(SourceWarning("files", source_ref, str(exc)))
                continue
            file_map[remote.file_id] = remote

    discovered_by_source: dict[int, tuple[str, str]] = {}

    for source_type in normalized_sources:
        if source_type == "files":
            continue

        try:
            items = _collect_source_items(client, course_id, source_type)
        except CanvasApiError as exc:
            warnings.append(
                SourceWarning(
                    source_type=source_type,
                    source_ref=f"{source_type}:course:{course_id}",
                    detail=f"Skipping {source_type} source: {exc}",
                )
            )
            continue

        for item in items:
            source_ref = _source_ref(source_type, item)
            file_ids = extract_file_ids_from_payload(item)
            if not file_ids and _has_unresolved_file_link(item):
                warnings.append(
                    SourceWarning(
                        source_type=source_type,
                        source_ref=source_ref,
                        detail="Found a file-like link but could not extract a Canvas file ID.",
                    )
                )
            for file_id in file_ids:
                discovered_by_source.setdefault(file_id, (source_type, source_ref))

    for file_id, (source_type, source_ref) in discovered_by_source.items():
        if file_id in file_map:
            continue
        try:
            payload = client.get_file(file_id)
            remote = _remote_file_from_payload(
                payload,
                course_id=course_id,
                folder_map=folder_map,
                source_type=source_type,
                source_ref=source_ref,
            )
            file_map[remote.file_id] = remote
        except CanvasApiError as exc:
            warnings.append(
                SourceWarning(
                    source_type=source_type,
                    source_ref=source_ref,
                    detail=f"Could not resolve file_id={file_id}: {exc}",
                )
            )

    ordered_files = sorted(file_map.values(), key=lambda item: item.file_id)
    return ordered_files, warnings


def warning_to_manifest_item(
    warning: SourceWarning,
    *,
    course_id: int,
) -> ManifestItem:
    return {
        "file_id": None,
        "course_id": course_id,
        "display_name": warning.detail,
        "source_type": warning.source_type,
        "source_ref": warning.source_ref,
        "remote_url": None,
        "local_path": None,
        "size": None,
        "updated_at": None,
        "etag": None,
        "sha256": None,
        "status": "unresolved",
        "error": warning.detail,
    }


def debug_dump_extraction(payload: Any) -> str:
    file_ids = sorted(extract_file_ids_from_payload(payload))
    return json.dumps({"file_ids": file_ids}, indent=2)
