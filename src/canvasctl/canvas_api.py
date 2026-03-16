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

    def __init__(self, message: str, *, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


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


@dataclass(slots=True)
class CourseGrade:
    """Overall grade for a single course enrollment."""

    course_id: int
    course_code: str
    course_name: str
    current_score: float | None
    current_grade: str | None


@dataclass(slots=True)
class AssignmentGrade:
    """Per-assignment grade with submission data."""

    assignment_id: int
    assignment_name: str
    course_id: int
    points_possible: float | None
    score: float | None
    grade: str | None
    submitted_at: str | None
    workflow_state: str | None


@dataclass(slots=True)
class UpcomingAssignment:
    """Assignment with due-date and submission info for upcoming views."""

    assignment_id: int
    assignment_name: str
    course_id: int
    course_name: str
    due_at: str | None
    lock_at: str | None
    unlock_at: str | None
    points_possible: float | None
    submission_types: list[str]
    has_submitted: bool
    html_url: str | None


@dataclass(slots=True)
class Announcement:
    """Course announcement."""

    id: int
    title: str
    message: str
    course_id: int
    posted_at: str | None
    author_name: str | None


@dataclass(slots=True)
class CalendarEvent:
    """Calendar event from Canvas."""

    id: int
    title: str
    description: str | None
    start_at: str | None
    end_at: str | None
    event_type: str | None
    context_name: str | None


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
            verify=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CanvasClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _sleep_for_retry(self, attempt: int, response: httpx.Response | None = None) -> None:
        base_delay = 0.5 * (2**attempt)
        if response is not None:
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    base_delay = float(retry_after)
                except ValueError:
                    pass
        jitter = random.uniform(0, 0.25 * base_delay)
        time.sleep(base_delay + jitter)

    def _request(
        self,
        method: str,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        data: Any = None,
        json: Any = None,
        files: Any = None,
    ) -> httpx.Response:
        target = self._normalize_request_target(path_or_url)
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.request(
                    method,
                    target,
                    params=params,
                    data=data,
                    json=json,
                    files=files,
                )
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
                    raise CanvasApiError(
                        f"Canvas request failed after retries ({response.status_code})",
                        detail=response.text[:200].strip(),
                    )
                self._sleep_for_retry(attempt, response)
                continue

            if response.status_code >= 400:
                raise CanvasApiError(
                    f"Canvas request failed ({response.status_code}) for {target}",
                    detail=response.text[:200].strip(),
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

    def post_json(
        self,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        data: Any = None,
        json: Any = None,
        files: Any = None,
    ) -> Any:
        response = self._request(
            "POST",
            path_or_url,
            params=params,
            data=data,
            json=json,
            files=files,
        )
        if not response.content:
            return {}
        return response.json()

    def put_json(
        self,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        data: Any = None,
        json: Any = None,
    ) -> Any:
        response = self._request(
            "PUT",
            path_or_url,
            params=params,
            data=data,
            json=json,
        )
        if not response.content:
            return {}
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

    def list_courses_with_grades(self, *, include_all: bool = False) -> list[CourseGrade]:
        params: dict[str, Any] = {
            "per_page": 100,
            "include[]": ["term", "total_scores"],
        }
        if not include_all:
            params["enrollment_state"] = "active"

        raw_courses = self.get_paginated("/courses", params=params)
        grades: list[CourseGrade] = []
        for item in raw_courses:
            enrollments = item.get("enrollments") or []
            student_enrollment: dict[str, Any] | None = None
            for enrollment in enrollments:
                if enrollment.get("type") == "student":
                    student_enrollment = enrollment
                    break

            grades.append(
                CourseGrade(
                    course_id=int(item["id"]),
                    course_code=item.get("course_code") or "",
                    course_name=item.get("name") or "",
                    current_score=(
                        student_enrollment.get("computed_current_score")
                        if student_enrollment
                        else None
                    ),
                    current_grade=(
                        student_enrollment.get("computed_current_grade")
                        if student_enrollment
                        else None
                    ),
                )
            )
        return grades

    def list_assignment_grades(self, course_id: int) -> list[AssignmentGrade]:
        raw = self.get_paginated(
            f"/courses/{course_id}/assignments",
            params={"per_page": 100, "include[]": ["submission"]},
        )
        grades: list[AssignmentGrade] = []
        for item in raw:
            submission = item.get("submission") or {}
            grades.append(
                AssignmentGrade(
                    assignment_id=int(item["id"]),
                    assignment_name=item.get("name") or "",
                    course_id=course_id,
                    points_possible=item.get("points_possible"),
                    score=submission.get("score"),
                    grade=submission.get("grade"),
                    submitted_at=submission.get("submitted_at"),
                    workflow_state=submission.get("workflow_state"),
                )
            )
        return grades

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

    def mark_module_item_done(
        self,
        course_id: int,
        module_id: int,
        module_item_id: int,
    ) -> dict[str, Any]:
        payload = self.put_json(
            f"/courses/{course_id}/modules/{module_id}/items/{module_item_id}/done",
        )
        if not isinstance(payload, dict):
            return {"result": payload}
        return payload

    def submit_assignment(
        self,
        course_id: int,
        assignment_id: int,
        *,
        submission_type: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        form_data: dict[str, Any] = {
            "submission[submission_type]": submission_type,
        }
        for key, value in body.items():
            if key == "file_ids" and isinstance(value, list):
                form_data["submission[file_ids][]"] = [str(file_id) for file_id in value]
                continue
            form_data[f"submission[{key}]"] = str(value)

        payload = self.post_json(
            f"/courses/{course_id}/assignments/{assignment_id}/submissions",
            data=form_data,
        )
        if not isinstance(payload, dict):
            return {"result": payload}
        return payload

    def init_assignment_file_upload(
        self,
        course_id: int,
        assignment_id: int,
        *,
        filename: str,
        size: int,
    ) -> dict[str, Any]:
        payload = self.post_json(
            f"/courses/{course_id}/assignments/{assignment_id}/submissions/self/files",
            data={
                "name": filename,
                "size": str(size),
            },
        )
        if not isinstance(payload, dict):
            raise CanvasApiError("Unexpected file upload init response from Canvas.")
        return payload

    def upload_file_to_canvas(
        self,
        upload_url: str,
        upload_params: dict[str, Any],
        local_path: Path,
    ) -> dict[str, Any]:
        if not local_path.is_file():
            raise CanvasApiError(f"File not found for upload: {local_path}")

        with local_path.open("rb") as handle:
            payload = self.post_json(
                upload_url,
                data=upload_params,
                files={"file": (local_path.name, handle)},
            )

        if not isinstance(payload, dict):
            raise CanvasApiError("Unexpected file upload response from Canvas.")
        return payload

    def get_file(self, file_id: int) -> dict[str, Any]:
        payload = self.get_json(f"/files/{file_id}")
        if not isinstance(payload, dict):
            raise CanvasApiError(f"Unexpected file payload for file_id={file_id}")
        return payload

    def download_file(self, url: str, destination: Path) -> tuple[int, str, str | None]:
        return self._stream_download_to_file(url, destination)

    def list_upcoming_assignments(self, course_id: int) -> list[UpcomingAssignment]:
        course_data = self.get_json(f"/courses/{course_id}")
        course_name = course_data.get("name") or ""

        raw = self.get_paginated(
            f"/courses/{course_id}/assignments",
            params={
                "per_page": 100,
                "include[]": ["submission"],
                "order_by": "due_at",
            },
        )
        assignments: list[UpcomingAssignment] = []
        for item in raw:
            submission = item.get("submission") or {}
            has_submitted = submission.get("workflow_state") not in (
                None,
                "unsubmitted",
            )
            assignments.append(
                UpcomingAssignment(
                    assignment_id=int(item["id"]),
                    assignment_name=item.get("name") or "",
                    course_id=course_id,
                    course_name=course_name,
                    due_at=item.get("due_at"),
                    lock_at=item.get("lock_at"),
                    unlock_at=item.get("unlock_at"),
                    points_possible=item.get("points_possible"),
                    submission_types=item.get("submission_types") or [],
                    has_submitted=has_submitted,
                    html_url=item.get("html_url"),
                )
            )
        return assignments

    def list_announcements(self, course_ids: list[int]) -> list[Announcement]:
        context_codes = [f"course_{cid}" for cid in course_ids]
        raw = self.get_paginated(
            "/announcements",
            params={
                "context_codes[]": context_codes,
                "per_page": 50,
            },
        )
        announcements: list[Announcement] = []
        for item in raw:
            # Extract course_id from context_code like "course_12345"
            context_code = item.get("context_code") or ""
            course_id = 0
            if context_code.startswith("course_"):
                try:
                    course_id = int(context_code[len("course_"):])
                except ValueError:
                    pass
            author = item.get("author") or {}
            announcements.append(
                Announcement(
                    id=int(item["id"]),
                    title=item.get("title") or "",
                    message=item.get("message") or "",
                    course_id=course_id,
                    posted_at=item.get("posted_at"),
                    author_name=author.get("display_name"),
                )
            )
        return announcements

    def list_calendar_events(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        context_codes: list[str] | None = None,
    ) -> list[CalendarEvent]:
        params: dict[str, Any] = {"per_page": 50}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if context_codes:
            params["context_codes[]"] = context_codes

        raw = self.get_paginated("/calendar_events", params=params)
        events: list[CalendarEvent] = []
        for item in raw:
            events.append(
                CalendarEvent(
                    id=int(item["id"]),
                    title=item.get("title") or "",
                    description=item.get("description"),
                    start_at=item.get("start_at"),
                    end_at=item.get("end_at"),
                    event_type=item.get("type"),
                    context_name=item.get("context_name"),
                )
            )
        return events

    def get_course_syllabus(self, course_id: int) -> dict[str, Any]:
        return self.get_json(
            f"/courses/{course_id}",
            params={"include[]": "syllabus_body"},
        )


def dedupe_courses(courses: Iterable[CourseSummary]) -> list[CourseSummary]:
    seen: set[int] = set()
    out: list[CourseSummary] = []
    for course in courses:
        if course.id in seen:
            continue
        seen.add(course.id)
        out.append(course)
    return out
