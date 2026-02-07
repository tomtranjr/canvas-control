from __future__ import annotations

import hashlib
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import httpx

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_NEXT_LINK_RE = re.compile(r"<([^>]+)>;\s*rel=\"next\"")


class CanvasApiError(RuntimeError):
    """Raised when Canvas returns a non-retryable API failure."""


class CanvasUnauthorizedError(CanvasApiError):
    """Raised for 401 responses."""


@dataclass(slots=True)
class CourseSummary:
    id: int
    course_code: str
    name: str
    workflow_state: str | None
    term_name: str | None
    start_at: str | None
    end_at: str | None


@dataclass(slots=True)
class RemoteFile:
    file_id: int
    course_id: int
    display_name: str
    filename: str
    folder_path: str
    size: int | None
    updated_at: str | None
    download_url: str
    source_type: str
    source_ref: str


class CanvasClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 30.0,
        max_retries: int = 5,
    ) -> None:
        normalized = base_url.rstrip("/")
        self.base_url = normalized
        self.api_root = normalized + "/api/v1"
        self.max_retries = max_retries
        self._client = httpx.Client(
            base_url=self.api_root,
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CanvasClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _sleep_for_retry(self, attempt: int, response: httpx.Response | None = None) -> None:
        if response is not None:
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    base_delay = float(retry_after)
                except ValueError:
                    base_delay = 0.5 * (2**attempt)
            else:
                base_delay = 0.5 * (2**attempt)
        else:
            base_delay = 0.5 * (2**attempt)
        jitter = random.uniform(0, 0.25 * base_delay)
        time.sleep(base_delay + jitter)

    def _request(
        self,
        method: str,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        target = self._normalize_request_target(path_or_url)
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.request(method, target, params=params)
            except httpx.TransportError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise CanvasApiError(f"Network failure: {exc}") from exc
                self._sleep_for_retry(attempt)
                continue

            if response.status_code == 401:
                raise CanvasUnauthorizedError("Canvas API rejected the token (401).")

            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt >= self.max_retries:
                    snippet = response.text[:200].strip()
                    raise CanvasApiError(
                        f"Canvas request failed after retries ({response.status_code}): {snippet}"
                    )
                self._sleep_for_retry(attempt, response)
                continue

            if response.status_code >= 400:
                snippet = response.text[:200].strip()
                raise CanvasApiError(
                    f"Canvas request failed ({response.status_code}) for {target}: {snippet}"
                )

            return response

        if last_error is not None:
            raise CanvasApiError(str(last_error)) from last_error
        raise CanvasApiError("Request failed with unknown error.")

    def _normalize_request_target(self, path_or_url: str) -> str:
        if path_or_url.startswith(("http://", "https://")):
            return path_or_url
        if path_or_url.startswith("/api/v1/"):
            return path_or_url[len("/api/v1/") :]
        return path_or_url.lstrip("/")

    def _stream_download_to_file(
        self,
        url: str,
        destination: Path,
    ) -> tuple[int, str, str | None]:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_path = destination.with_name(destination.name + ".part")

        for attempt in range(self.max_retries + 1):
            try:
                with self._client.stream("GET", url) as response:
                    if response.status_code == 401:
                        raise CanvasUnauthorizedError("Canvas API rejected the token (401).")

                    if response.status_code in RETRYABLE_STATUS_CODES:
                        if attempt >= self.max_retries:
                            raise CanvasApiError(
                                f"Download failed after retries ({response.status_code}) for {url}"
                            )
                        self._sleep_for_retry(attempt, response)
                        continue

                    if response.status_code >= 400:
                        snippet = response.text[:200].strip()
                        raise CanvasApiError(
                            f"Download failed ({response.status_code}) for {url}: {snippet}"
                        )

                    file_hash = hashlib.sha256()
                    bytes_written = 0
                    with temp_path.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            if not chunk:
                                continue
                            handle.write(chunk)
                            file_hash.update(chunk)
                            bytes_written += len(chunk)

                    temp_path.replace(destination)
                    etag = response.headers.get("etag")
                    return bytes_written, file_hash.hexdigest(), etag

            except httpx.TransportError as exc:
                if attempt >= self.max_retries:
                    raise CanvasApiError(f"Download network failure for {url}: {exc}") from exc
                self._sleep_for_retry(attempt)
            finally:
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)

        raise CanvasApiError(f"Download failed for {url}")

    def get_json(
        self,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        response = self._request("GET", path_or_url, params=params)
        return response.json()

    def get_paginated(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> list[Any]:
        results: list[Any] = []
        next_url: str | None = path
        next_params = dict(params or {})
        seen_targets: set[str] = set()

        while next_url:
            current_target = self._normalize_request_target(next_url)
            if current_target in seen_targets:
                raise CanvasApiError(
                    f"Pagination loop detected for {path}: repeated next link {next_url!r}"
                )
            seen_targets.add(current_target)

            response = self._request("GET", next_url, params=next_params)
            payload = response.json()
            if isinstance(payload, list):
                results.extend(payload)
            else:
                results.append(payload)

            link_header = response.headers.get("link", "")
            match = _NEXT_LINK_RE.search(link_header)
            next_url = match.group(1) if match else None
            next_params = None

        return results

    def list_courses(self, *, include_all: bool = False) -> list[CourseSummary]:
        params: dict[str, Any] = {
            "per_page": 100,
            "include[]": ["term", "total_students"],
        }
        if not include_all:
            params["enrollment_state"] = "active"

        raw_courses = self.get_paginated("/courses", params=params)
        courses: list[CourseSummary] = []
        for item in raw_courses:
            term = item.get("term") or {}
            courses.append(
                CourseSummary(
                    id=int(item["id"]),
                    course_code=item.get("course_code") or "",
                    name=item.get("name") or "",
                    workflow_state=item.get("workflow_state"),
                    term_name=term.get("name"),
                    start_at=item.get("start_at"),
                    end_at=item.get("end_at"),
                )
            )
        return courses

    def list_course_files(self, course_id: int) -> list[dict[str, Any]]:
        return self.get_paginated(f"/courses/{course_id}/files", params={"per_page": 100})

    def list_course_folders(self, course_id: int) -> dict[int, str]:
        folder_map: dict[int, str] = {}
        folders = self.get_paginated(f"/courses/{course_id}/folders", params={"per_page": 100})
        for folder in folders:
            folder_id = folder.get("id")
            if folder_id is None:
                continue
            full_name = folder.get("full_name") or folder.get("name") or ""
            folder_map[int(folder_id)] = str(full_name).strip("/")
        return folder_map

    def list_assignments(self, course_id: int) -> list[dict[str, Any]]:
        return self.get_paginated(
            f"/courses/{course_id}/assignments",
            params={"per_page": 100},
        )

    def list_discussions(self, course_id: int) -> list[dict[str, Any]]:
        return self.get_paginated(
            f"/courses/{course_id}/discussion_topics",
            params={"per_page": 100},
        )

    def list_pages(self, course_id: int) -> list[dict[str, Any]]:
        pages = self.get_paginated(f"/courses/{course_id}/pages", params={"per_page": 100})
        detailed_pages: list[dict[str, Any]] = []
        for page in pages:
            page_url = page.get("url")
            if not page_url:
                continue
            detail = self.get_json(f"/courses/{course_id}/pages/{page_url}")
            detailed_pages.append(detail)
        return detailed_pages

    def list_modules(self, course_id: int) -> list[dict[str, Any]]:
        return self.get_paginated(
            f"/courses/{course_id}/modules",
            params={"per_page": 100, "include[]": ["items"]},
        )

    def get_file(self, file_id: int) -> dict[str, Any]:
        payload = self.get_json(f"/files/{file_id}")
        if not isinstance(payload, dict):
            raise CanvasApiError(f"Unexpected file payload for file_id={file_id}")
        return payload

    def download_file(self, url: str, destination: Path) -> tuple[int, str, str | None]:
        return self._stream_download_to_file(url, destination)


def dedupe_courses(courses: Iterable[CourseSummary]) -> list[CourseSummary]:
    seen: set[int] = set()
    out: list[CourseSummary] = []
    for course in courses:
        if course.id in seen:
            continue
        seen.add(course.id)
        out.append(course)
    return out
