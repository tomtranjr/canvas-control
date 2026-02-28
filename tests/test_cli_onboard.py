from __future__ import annotations

import io
from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

from canvasctl.canvas_api import CanvasApiError, CanvasUnauthorizedError, CourseSummary
from canvasctl.cli import app
from canvasctl.config import AppConfig
from canvasctl.onboard import (
    OnboardResult,
    _step_base_url,
    _step_download_paths,
    _step_show_courses,
    _step_summary,
    _step_token_and_verify,
    run_onboard,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SAMPLE_COURSES = [
    CourseSummary(
        id=100,
        course_code="BIO101",
        name="Biology",
        workflow_state="available",
        term_name="Spring 2026",
        start_at=None,
        end_at=None,
    ),
    CourseSummary(
        id=200,
        course_code="CS201",
        name="Algorithms",
        workflow_state="available",
        term_name="Spring 2026",
        start_at=None,
        end_at=None,
    ),
]


class _FakePrompt:
    def __init__(self, answer):
        self._answer = answer

    def ask(self):
        return self._answer


class FakeQuestionary:
    """Returns preset answers in order for each questionary prompt call."""

    def __init__(self, *answers):
        self._answers = list(answers)
        self._index = 0

    def _next(self, label: str = "") -> _FakePrompt:
        if self._index >= len(self._answers):
            raise AssertionError(
                f"FakeQuestionary exhausted at index {self._index} "
                f"(next prompt label: {label!r})"
            )
        answer = self._answers[self._index]
        self._index += 1
        return _FakePrompt(answer)

    def text(self, label: str = "", **kwargs) -> _FakePrompt:
        return self._next(label)

    def password(self, label: str = "", **kwargs) -> _FakePrompt:
        return self._next(label)

    def confirm(self, label: str = "", **kwargs) -> _FakePrompt:
        return self._next(label)

    def select(self, label: str = "", **kwargs) -> _FakePrompt:
        return self._next(label)

    def checkbox(self, label: str = "", **kwargs) -> _FakePrompt:
        return self._next(label)

    class Choice:
        def __init__(self, title: str = "", value=None, checked: bool = False):
            self.title = title
            self.value = value
            self.checked = checked


class FakeClient:
    def __init__(self, courses=None, raise_on_first_call=None):
        self._courses = courses if courses is not None else SAMPLE_COURSES
        self._raise_on_first_call = raise_on_first_call
        self._call_count = 0
        self.closed = False

    def list_courses(self, *, include_all: bool = False):
        self._call_count += 1
        if self._raise_on_first_call and self._call_count == 1:
            raise self._raise_on_first_call
        return self._courses

    def close(self) -> None:
        self.closed = True


def _console() -> Console:
    return Console(file=io.StringIO(), no_color=True, width=120)


def _console_out(console: Console) -> str:
    return console.file.getvalue()  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# CLI registration
# ---------------------------------------------------------------------------


def test_onboard_command_registered():
    """The onboard command exists and its help is accessible."""
    result = CliRunner().invoke(app, ["onboard", "--help"])
    assert result.exit_code == 0
    assert "setup wizard" in result.output.lower()


def test_onboard_keyboard_interrupt_exits_cleanly(monkeypatch):
    """KeyboardInterrupt inside onboard prints 'Setup cancelled' and exits 1."""

    def raise_kbi(_console):
        raise KeyboardInterrupt

    monkeypatch.setattr("canvasctl.onboard.run_onboard", raise_kbi)
    result = CliRunner().invoke(app, ["onboard"])
    assert result.exit_code == 1
    assert "cancelled" in result.output.lower()


# ---------------------------------------------------------------------------
# Step 1: Canvas URL
# ---------------------------------------------------------------------------


def test_step_base_url_already_set_keep(monkeypatch):
    """Existing URL + user keeps it: set_base_url is NOT called."""
    set_called = []
    monkeypatch.setattr(
        "canvasctl.onboard.set_base_url",
        lambda url: set_called.append(url) or AppConfig(base_url=url),
    )
    fq = FakeQuestionary(True)  # "Keep this URL?"
    monkeypatch.setattr("canvasctl.onboard._load_questionary", lambda: fq)

    cfg = AppConfig(base_url="https://canvas.test")
    out_cfg = _step_base_url(_console(), cfg, OnboardResult())

    assert not set_called
    assert out_cfg.base_url == "https://canvas.test"


def test_step_base_url_already_set_change(monkeypatch):
    """Existing URL + user declines: new URL prompted and saved."""
    saved = []
    monkeypatch.setattr(
        "canvasctl.onboard.set_base_url",
        lambda url: saved.append(url) or AppConfig(base_url=url),
    )
    fq = FakeQuestionary(False, "https://new.canvas.example.com")
    monkeypatch.setattr("canvasctl.onboard._load_questionary", lambda: fq)

    cfg = AppConfig(base_url="https://old.canvas.test")
    out_cfg = _step_base_url(_console(), cfg, OnboardResult())

    assert saved == ["https://new.canvas.example.com"]
    assert out_cfg.base_url == "https://new.canvas.example.com"


def test_step_base_url_not_set_prompts_and_saves(monkeypatch):
    """No URL configured: prompts for one and saves it."""
    saved = []
    monkeypatch.setattr(
        "canvasctl.onboard.set_base_url",
        lambda url: saved.append(url) or AppConfig(base_url=url),
    )
    fq = FakeQuestionary("https://school.instructure.com")
    monkeypatch.setattr("canvasctl.onboard._load_questionary", lambda: fq)

    out_cfg = _step_base_url(_console(), AppConfig(), OnboardResult())

    assert saved == ["https://school.instructure.com"]
    assert out_cfg.base_url == "https://school.instructure.com"


def test_step_base_url_empty_input_skips(monkeypatch):
    """Empty URL entry leaves config unchanged (no save, base_url stays None)."""
    set_called = []
    monkeypatch.setattr(
        "canvasctl.onboard.set_base_url",
        lambda url: set_called.append(url),
    )
    fq = FakeQuestionary("")  # empty
    monkeypatch.setattr("canvasctl.onboard._load_questionary", lambda: fq)

    out_cfg = _step_base_url(_console(), AppConfig(), OnboardResult())

    assert not set_called
    assert out_cfg.base_url is None


# ---------------------------------------------------------------------------
# Step 2: Token & verification
# ---------------------------------------------------------------------------


def test_step_token_env_accepted(monkeypatch):
    """CANVAS_TOKEN set + user accepts: no password prompt, returns open client."""
    monkeypatch.setenv("CANVAS_TOKEN", "env-token-xyz")
    fake = FakeClient()
    monkeypatch.setattr("canvasctl.onboard.CanvasClient", lambda base_url, token: fake)
    fq = FakeQuestionary(True)  # "Use CANVAS_TOKEN?"
    monkeypatch.setattr("canvasctl.onboard._load_questionary", lambda: fq)

    result = OnboardResult()
    client = _step_token_and_verify(_console(), "https://canvas.test", result)

    assert client is fake
    assert result.token_source == "env"
    client.close()


def test_step_token_env_declined_uses_password_prompt(monkeypatch):
    """CANVAS_TOKEN set but user declines: password prompt used instead."""
    monkeypatch.setenv("CANVAS_TOKEN", "env-token-xyz")
    fake = FakeClient()
    monkeypatch.setattr("canvasctl.onboard.CanvasClient", lambda base_url, token: fake)
    fq = FakeQuestionary(False, "manual-token-abc")  # decline env, enter manually
    monkeypatch.setattr("canvasctl.onboard._load_questionary", lambda: fq)

    result = OnboardResult()
    client = _step_token_and_verify(_console(), "https://canvas.test", result)

    assert client is fake
    assert result.token_source == "prompt"
    client.close()


def test_step_token_no_env_prompts_password(monkeypatch):
    """No CANVAS_TOKEN: password prompt shown and token verified."""
    monkeypatch.delenv("CANVAS_TOKEN", raising=False)
    fake = FakeClient()
    monkeypatch.setattr("canvasctl.onboard.CanvasClient", lambda base_url, token: fake)
    fq = FakeQuestionary("my-secret-token")
    monkeypatch.setattr("canvasctl.onboard._load_questionary", lambda: fq)

    result = OnboardResult()
    client = _step_token_and_verify(_console(), "https://canvas.test", result)

    assert client is fake
    assert result.token_source == "prompt"
    client.close()


def test_step_token_empty_password_returns_none(monkeypatch):
    """Empty password input skips verification and returns None."""
    monkeypatch.delenv("CANVAS_TOKEN", raising=False)
    fq = FakeQuestionary("")
    monkeypatch.setattr("canvasctl.onboard._load_questionary", lambda: fq)

    client = _step_token_and_verify(_console(), "https://canvas.test", OnboardResult())
    assert client is None


def test_step_token_401_retry_with_new_token_succeeds(monkeypatch):
    """401 on first attempt: user retries with different token, second attempt succeeds."""
    monkeypatch.delenv("CANVAS_TOKEN", raising=False)

    call_count = [0]

    class _RetryClient:
        def list_courses(self, *, include_all: bool = False):
            call_count[0] += 1
            if call_count[0] == 1:
                raise CanvasUnauthorizedError("bad")
            return SAMPLE_COURSES

        def close(self) -> None:
            pass

    monkeypatch.setattr("canvasctl.onboard.CanvasClient", lambda *_a, **_kw: _RetryClient())
    fq = FakeQuestionary("bad-token", True, "good-token")  # enter, retry yes, new token
    monkeypatch.setattr("canvasctl.onboard._load_questionary", lambda: fq)

    client = _step_token_and_verify(_console(), "https://canvas.test", OnboardResult())

    assert client is not None
    assert call_count[0] == 2


def test_step_token_401_no_retry_returns_none(monkeypatch):
    """401 on first attempt, user declines retry: returns None."""
    monkeypatch.delenv("CANVAS_TOKEN", raising=False)
    fake = FakeClient(raise_on_first_call=CanvasUnauthorizedError("bad"))
    monkeypatch.setattr("canvasctl.onboard.CanvasClient", lambda *_a, **_kw: fake)
    fq = FakeQuestionary("bad-token", False)  # enter token, decline retry
    monkeypatch.setattr("canvasctl.onboard._load_questionary", lambda: fq)

    client = _step_token_and_verify(_console(), "https://canvas.test", OnboardResult())
    assert client is None


# ---------------------------------------------------------------------------
# Step 3: Show courses
# ---------------------------------------------------------------------------


def test_step_show_courses_renders_table():
    """Courses table is printed and courses_count is set on result."""
    console = _console()
    result = OnboardResult()
    courses = _step_show_courses(console, FakeClient(), result)

    assert result.courses_count == 2
    output = _console_out(console)
    assert "BIO101" in output
    assert "CS201" in output
    assert len(courses) == 2


def test_step_show_courses_empty_prints_warning():
    """No active courses prints a warning and returns empty list."""
    console = _console()
    result = OnboardResult()
    courses = _step_show_courses(console, FakeClient(courses=[]), result)

    assert courses == []
    assert result.courses_count == 0
    assert "no active courses" in _console_out(console).lower()


# ---------------------------------------------------------------------------
# Step 4: Download paths
# ---------------------------------------------------------------------------


def test_step_download_single_path_saves_global(monkeypatch, tmp_path):
    """Choosing 'single' prompts for a path and calls set_default_destination."""
    saved = []
    monkeypatch.setattr(
        "canvasctl.onboard.set_default_destination",
        lambda p: saved.append(p) or AppConfig(default_dest=str(p)),
    )
    fq = FakeQuestionary("single", str(tmp_path / "dl"))
    monkeypatch.setattr("canvasctl.onboard._load_questionary", lambda: fq)

    result = OnboardResult()
    _step_download_paths(_console(), AppConfig(), SAMPLE_COURSES, result)

    assert saved == [str(tmp_path / "dl")]
    assert result.path_strategy == "single"
    assert result.default_dest == str(tmp_path / "dl")


def test_step_download_per_course_checkbox_then_paths(monkeypatch, tmp_path):
    """Per-course: checkbox selects courses, path prompted for each selected."""
    saved = {}
    monkeypatch.setattr(
        "canvasctl.onboard.set_course_path",
        lambda cid, p: saved.update({str(cid): p}) or AppConfig(),
    )
    fq = FakeQuestionary(
        "per_course",
        [SAMPLE_COURSES[0]],       # checkbox: select only BIO101
        str(tmp_path / "bio"),     # path for BIO101
    )
    monkeypatch.setattr("canvasctl.onboard._load_questionary", lambda: fq)

    result = OnboardResult()
    _step_download_paths(_console(), AppConfig(), SAMPLE_COURSES, result)

    assert "100" in saved
    assert "200" not in saved
    assert result.path_strategy == "per_course"


def test_step_download_per_course_empty_path_skips_course(monkeypatch, tmp_path):
    """Empty path for a course skips set_course_path for that course only."""
    saved = {}
    monkeypatch.setattr(
        "canvasctl.onboard.set_course_path",
        lambda cid, p: saved.update({str(cid): p}) or AppConfig(),
    )
    fq = FakeQuestionary(
        "per_course",
        SAMPLE_COURSES,             # select all
        "",                         # blank for BIO101 → skip
        str(tmp_path / "cs"),       # path for CS201
    )
    monkeypatch.setattr("canvasctl.onboard._load_questionary", lambda: fq)

    result = OnboardResult()
    _step_download_paths(_console(), AppConfig(), SAMPLE_COURSES, result)

    assert "100" not in saved  # BIO101 was skipped
    assert "200" in saved      # CS201 was saved


def test_step_download_default_no_config_changes(monkeypatch):
    """Choosing 'default' makes no config changes and sets path_strategy."""
    mutations = []
    monkeypatch.setattr("canvasctl.onboard.set_default_destination", lambda p: mutations.append(p))
    monkeypatch.setattr("canvasctl.onboard.set_course_path", lambda c, p: mutations.append((c, p)))
    fq = FakeQuestionary("default")
    monkeypatch.setattr("canvasctl.onboard._load_questionary", lambda: fq)

    result = OnboardResult()
    _step_download_paths(_console(), AppConfig(), SAMPLE_COURSES, result)

    assert not mutations
    assert result.path_strategy == "default"


def test_step_download_skip_no_config_changes(monkeypatch):
    """Choosing 'skip' makes no config changes."""
    mutations = []
    monkeypatch.setattr("canvasctl.onboard.set_default_destination", lambda p: mutations.append(p))
    monkeypatch.setattr("canvasctl.onboard.set_course_path", lambda c, p: mutations.append((c, p)))
    fq = FakeQuestionary("skip")
    monkeypatch.setattr("canvasctl.onboard._load_questionary", lambda: fq)

    result = OnboardResult()
    _step_download_paths(_console(), AppConfig(), SAMPLE_COURSES, result)

    assert not mutations
    assert result.path_strategy == "skipped"


# ---------------------------------------------------------------------------
# Step 5: Summary
# ---------------------------------------------------------------------------


def test_summary_shows_export_reminder_for_manual_token():
    """Manually-entered token → 'export CANVAS_TOKEN' hint appears in summary."""
    console = _console()
    _step_summary(
        console,
        OnboardResult(
            base_url="https://canvas.test",
            token_source="prompt",
            courses_count=2,
            path_strategy="default",
        ),
    )
    assert "export CANVAS_TOKEN" in _console_out(console)


def test_summary_no_export_reminder_for_env_token():
    """Env-sourced token → no 'export CANVAS_TOKEN' hint in summary."""
    console = _console()
    _step_summary(
        console,
        OnboardResult(
            base_url="https://canvas.test",
            token_source="env",
            courses_count=3,
            path_strategy="single",
            default_dest="/home/user/Downloads",
        ),
    )
    assert "export CANVAS_TOKEN" not in _console_out(console)


# ---------------------------------------------------------------------------
# run_onboard orchestration
# ---------------------------------------------------------------------------


def test_run_onboard_no_base_url_skips_downstream_steps(monkeypatch):
    """If step 1 results in no base_url, token/courses/paths steps are not run."""
    monkeypatch.setattr("canvasctl.onboard.load_config", lambda: AppConfig())
    fq = FakeQuestionary("")  # empty URL → stays None
    monkeypatch.setattr("canvasctl.onboard._load_questionary", lambda: fq)

    client_created = []
    monkeypatch.setattr(
        "canvasctl.onboard.CanvasClient",
        lambda *a, **kw: client_created.append(True),
    )

    run_onboard(_console())
    assert not client_created


def test_run_onboard_client_always_closed_on_downstream_exception(monkeypatch):
    """The CanvasClient is closed even when a later step raises."""
    monkeypatch.setattr(
        "canvasctl.onboard.load_config",
        lambda: AppConfig(base_url="https://canvas.test"),
    )
    fake = FakeClient()

    monkeypatch.setattr("canvasctl.onboard._step_base_url", lambda *_a: AppConfig(base_url="https://canvas.test"))
    monkeypatch.setattr("canvasctl.onboard._step_token_and_verify", lambda *_a: fake)
    monkeypatch.setattr("canvasctl.onboard._step_show_courses", lambda *_a: (_ for _ in ()).throw(RuntimeError("boom")))

    try:
        run_onboard(_console())
    except RuntimeError:
        pass

    assert fake.closed


def test_run_onboard_env_token_default_paths_succeeds(monkeypatch):
    """Full happy-path: env token, keep URL, default download paths."""
    monkeypatch.setenv("CANVAS_TOKEN", "test-token")
    monkeypatch.setattr(
        "canvasctl.onboard.load_config",
        lambda: AppConfig(base_url="https://canvas.test"),
    )
    fake = FakeClient()
    monkeypatch.setattr("canvasctl.onboard.CanvasClient", lambda *_a, **_kw: fake)
    fq = FakeQuestionary(
        True,       # Keep URL?
        True,       # Use CANVAS_TOKEN?
        "default",  # Download path setup
    )
    monkeypatch.setattr("canvasctl.onboard._load_questionary", lambda: fq)

    run_onboard(_console())  # should not raise
    assert fake.closed


# ---------------------------------------------------------------------------
# New tests for PR #21 review findings
# ---------------------------------------------------------------------------


def test_onboard_eoferror_exits_cleanly(monkeypatch):
    """EOFError inside run_onboard prints 'cancelled' and exits with code 1."""

    def raise_eof(_console):
        raise EOFError

    monkeypatch.setattr("canvasctl.onboard.run_onboard", raise_eof)
    result = CliRunner().invoke(app, ["onboard"])
    assert result.exit_code == 1
    assert "cancelled" in result.output.lower()


def test_step_token_401_all_retries_exhausted(monkeypatch):
    """3 consecutive 401s exhaust all retries and return None."""
    monkeypatch.delenv("CANVAS_TOKEN", raising=False)

    call_count = [0]

    class _Always401:
        def list_courses(self, *, include_all: bool = False):
            call_count[0] += 1
            raise CanvasUnauthorizedError("bad")

        def close(self) -> None:
            pass

    monkeypatch.setattr("canvasctl.onboard.CanvasClient", lambda *_a, **_kw: _Always401())
    # t1 → 401, retry=True, t2 → 401, retry=True, t3 → 401 (3rd attempt, no more retries)
    fq = FakeQuestionary("t1", True, "t2", True, "t3")
    monkeypatch.setattr("canvasctl.onboard._load_questionary", lambda: fq)

    console = _console()
    client = _step_token_and_verify(console, "https://canvas.test", OnboardResult())

    assert client is None
    assert "too many failed attempts" in _console_out(console).lower()


def test_step_token_canvas_api_error_retry_succeeds(monkeypatch):
    """First CanvasClient raises CanvasApiError; retry with new token succeeds."""
    monkeypatch.delenv("CANVAS_TOKEN", raising=False)

    call_count = [0]

    class _RetryClient:
        def list_courses(self, *, include_all: bool = False):
            call_count[0] += 1
            if call_count[0] == 1:
                raise CanvasApiError("timeout")
            return SAMPLE_COURSES

        def close(self) -> None:
            pass

    monkeypatch.setattr("canvasctl.onboard.CanvasClient", lambda *_a, **_kw: _RetryClient())
    # enter token, api error → retry=True, enter new token
    fq = FakeQuestionary("bad-token", True, "good-token")
    monkeypatch.setattr("canvasctl.onboard._load_questionary", lambda: fq)

    client = _step_token_and_verify(_console(), "https://canvas.test", OnboardResult())
    assert client is not None


def test_step_token_canvas_api_error_no_retry(monkeypatch):
    """CanvasApiError on first attempt, user declines retry: returns None."""
    monkeypatch.delenv("CANVAS_TOKEN", raising=False)
    fake = FakeClient(raise_on_first_call=CanvasApiError("timeout"))
    monkeypatch.setattr("canvasctl.onboard.CanvasClient", lambda *_a, **_kw: fake)
    fq = FakeQuestionary("bad-token", False)  # enter token, decline retry
    monkeypatch.setattr("canvasctl.onboard._load_questionary", lambda: fq)

    client = _step_token_and_verify(_console(), "https://canvas.test", OnboardResult())
    assert client is None


def test_step_show_courses_api_error_returns_empty(monkeypatch):
    """API error in _step_show_courses returns [] and prints error message."""
    console = _console()
    result = OnboardResult()

    fake = FakeClient(raise_on_first_call=CanvasApiError("timeout"))
    courses = _step_show_courses(console, fake, result)

    assert courses == []
    assert result.courses_count == 0
    assert "could not fetch" in _console_out(console).lower()


def test_run_onboard_corrupt_config_falls_back_to_defaults(monkeypatch):
    """Corrupt config (ConfigError from load_config) is caught; onboard continues with defaults."""
    from canvasctl.config import ConfigError

    def _raise_config_error():
        raise ConfigError("bad toml")

    monkeypatch.setattr("canvasctl.onboard.load_config", _raise_config_error)
    fq = FakeQuestionary("")  # empty URL → skip downstream steps
    monkeypatch.setattr("canvasctl.onboard._load_questionary", lambda: fq)

    console = _console()
    run_onboard(console)  # must not raise
    assert "starting with defaults" in _console_out(console).lower()


def test_step_token_empty_retry_token_returns_none(monkeypatch):
    """Token fails 401 once; user says retry=True but enters blank password → returns None."""
    monkeypatch.delenv("CANVAS_TOKEN", raising=False)
    fake = FakeClient(raise_on_first_call=CanvasUnauthorizedError("bad"))
    monkeypatch.setattr("canvasctl.onboard.CanvasClient", lambda *_a, **_kw: fake)
    fq = FakeQuestionary("bad-token", True, "")  # enter token, retry yes, blank
    monkeypatch.setattr("canvasctl.onboard._load_questionary", lambda: fq)

    client = _step_token_and_verify(_console(), "https://canvas.test", OnboardResult())
    assert client is None
