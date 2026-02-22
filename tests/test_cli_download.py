from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from canvasctl.canvas_api import CourseSummary
from canvasctl.cli import app
from canvasctl.config import AppConfig
from canvasctl.interactive import InteractiveSelection


class FakeClient:
    def list_courses(self, *, include_all: bool):
        assert include_all is True
        return [
            CourseSummary(
                id=1631791,
                course_code="MSDS-697-01",
                name="Distributed Data Systems",
                workflow_state="available",
                term_name="Spring 2026",
                start_at=None,
                end_at=None,
            )
        ]


def _setup_common(monkeypatch, capture: dict[str, object]) -> None:
    monkeypatch.setattr("canvasctl.cli._load_config_or_fail", lambda: AppConfig(base_url="https://canvas.test"))
    monkeypatch.setattr("canvasctl.cli._resolve_base_url_or_fail", lambda _cfg, _override: "https://canvas.test")
    monkeypatch.setattr("canvasctl.cli._run_with_client", lambda _base_url, action: action(FakeClient()))

    def fake_download_for_courses(**kwargs):
        capture.update(kwargs)
        return 0

    monkeypatch.setattr("canvasctl.cli._download_for_courses", fake_download_for_courses)


def test_download_run_default_overwrite_false(monkeypatch):
    runner = CliRunner()
    capture: dict[str, object] = {}
    _setup_common(monkeypatch, capture)

    result = runner.invoke(app, ["download", "run", "--course", "1631791"])

    assert result.exit_code == 0
    assert capture["force"] is False


def test_download_run_overwrite_true(monkeypatch):
    runner = CliRunner()
    capture: dict[str, object] = {}
    _setup_common(monkeypatch, capture)

    result = runner.invoke(
        app,
        ["download", "run", "--course", "1631791", "--overwrite", "true"],
    )

    assert result.exit_code == 0
    assert capture["force"] is True


def test_download_run_overwrite_false(monkeypatch):
    runner = CliRunner()
    capture: dict[str, object] = {}
    _setup_common(monkeypatch, capture)

    result = runner.invoke(
        app,
        ["download", "run", "--course", "1631791", "--overwrite=false"],
    )

    assert result.exit_code == 0
    assert capture["force"] is False


def test_download_run_force_conflicts_with_overwrite_false(monkeypatch):
    runner = CliRunner()
    capture: dict[str, object] = {}
    _setup_common(monkeypatch, capture)

    result = runner.invoke(
        app,
        ["download", "run", "--course", "1631791", "--force", "--overwrite", "false"],
    )

    assert result.exit_code != 0
    assert "Conflicting options" in result.output


def test_download_run_uses_dest_override(monkeypatch, tmp_path):
    runner = CliRunner()
    capture: dict[str, object] = {}
    _setup_common(monkeypatch, capture)

    destination = tmp_path / "custom-downloads"
    result = runner.invoke(
        app,
        ["download", "run", "--course", "1631791", "--dest", str(destination)],
    )

    assert result.exit_code == 0
    assert capture["dest_root"] == destination.resolve()


def test_download_run_export_dest_requires_dest(monkeypatch):
    runner = CliRunner()
    capture: dict[str, object] = {}
    _setup_common(monkeypatch, capture)

    result = runner.invoke(
        app,
        ["download", "run", "--course", "1631791", "--export-dest"],
    )

    assert result.exit_code != 0
    assert "--export-dest requires --dest" in result.output


def test_download_run_export_dest_persists_destination(monkeypatch, tmp_path):
    runner = CliRunner()
    capture: dict[str, object] = {}
    _setup_common(monkeypatch, capture)

    saved: dict[str, Path] = {}

    def fake_set_default_destination(path: Path) -> AppConfig:
        saved["path"] = path
        return AppConfig(
            base_url="https://canvas.test",
            default_dest=str(path),
            default_concurrency=12,
        )

    monkeypatch.setattr("canvasctl.cli.set_default_destination", fake_set_default_destination)

    destination = tmp_path / "persisted-downloads"
    result = runner.invoke(
        app,
        [
            "download",
            "run",
            "--course",
            "1631791",
            "--dest",
            str(destination),
            "--export-dest",
        ],
    )

    assert result.exit_code == 0
    assert saved["path"] == destination.resolve()
    assert "Saved default download path" in result.output


def test_download_interactive_export_dest_requires_dest(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr("canvasctl.cli._load_config_or_fail", lambda: AppConfig(base_url="https://canvas.test"))
    monkeypatch.setattr("canvasctl.cli._resolve_base_url_or_fail", lambda _cfg, _override: "https://canvas.test")

    result = runner.invoke(app, ["download", "interactive", "--export-dest"])

    assert result.exit_code != 0
    assert "--export-dest requires --dest" in result.output


def test_download_interactive_handles_prompt_errors_without_traceback(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr("canvasctl.cli._load_config_or_fail", lambda: AppConfig(base_url="https://canvas.test"))
    monkeypatch.setattr("canvasctl.cli._resolve_base_url_or_fail", lambda _cfg, _override: "https://canvas.test")

    class InteractiveClient:
        def list_courses(self, *, include_all: bool):
            assert include_all is False
            return [
                CourseSummary(
                    id=1631791,
                    course_code="MSDS-697-01",
                    name="Distributed Data Systems",
                    workflow_state="available",
                    term_name="Spring 2026",
                    start_at=None,
                    end_at=None,
                )
            ]

    monkeypatch.setattr(
        "canvasctl.cli._run_with_client",
        lambda _base_url, action: action(InteractiveClient()),
    )
    monkeypatch.setattr(
        "canvasctl.cli.prompt_interactive_selection",
        lambda _courses: (_ for _ in ()).throw(RuntimeError("No courses selected.")),
    )

    result = runner.invoke(app, ["download", "interactive"])

    assert result.exit_code == 1
    assert "No courses selected." in result.output
    assert "Traceback" not in result.output


def test_download_interactive_passes_selected_courses_and_sources(monkeypatch, tmp_path):
    runner = CliRunner()
    monkeypatch.setattr("canvasctl.cli._load_config_or_fail", lambda: AppConfig(base_url="https://canvas.test"))
    monkeypatch.setattr("canvasctl.cli._resolve_base_url_or_fail", lambda _cfg, _override: "https://canvas.test")

    class InteractiveClient:
        def list_courses(self, *, include_all: bool):
            assert include_all is False
            return [
                CourseSummary(
                    id=1631791,
                    course_code="MSDS-697-01",
                    name="Distributed Data Systems",
                    workflow_state="available",
                    term_name="Spring 2026",
                    start_at=None,
                    end_at=None,
                ),
                CourseSummary(
                    id=2000000,
                    course_code="MSDS-600-01",
                    name="Another Course",
                    workflow_state="available",
                    term_name="Spring 2026",
                    start_at=None,
                    end_at=None,
                ),
            ]

    capture: dict[str, object] = {}

    monkeypatch.setattr(
        "canvasctl.cli._run_with_client",
        lambda _base_url, action: action(InteractiveClient()),
    )
    monkeypatch.setattr(
        "canvasctl.cli.prompt_interactive_selection",
        lambda _courses: InteractiveSelection(
            course_ids=[1631791, 9999999],
            sources=["files", "assignments"],
        ),
    )

    def fake_download_for_courses(**kwargs):
        capture.update(kwargs)
        return 0

    monkeypatch.setattr("canvasctl.cli._download_for_courses", fake_download_for_courses)

    destination = tmp_path / "interactive-downloads"
    result = runner.invoke(
        app,
        ["download", "interactive", "--dest", str(destination), "--force"],
    )

    assert result.exit_code == 0
    assert [item.id for item in capture["selected_courses"]] == [1631791]
    assert capture["sources"] == ["files", "assignments"]
    assert capture["dest_root"] == destination.resolve()
    assert capture["force"] is True


def test_download_run_uses_course_path_when_configured(monkeypatch, tmp_path):
    runner = CliRunner()
    capture: dict[str, object] = {}

    course_dest = tmp_path / "my-class"
    monkeypatch.setattr(
        "canvasctl.cli._load_config_or_fail",
        lambda: AppConfig(
            base_url="https://canvas.test",
            course_paths={"1631791": str(course_dest)},
        ),
    )
    monkeypatch.setattr("canvasctl.cli._resolve_base_url_or_fail", lambda _cfg, _override: "https://canvas.test")
    monkeypatch.setattr("canvasctl.cli._run_with_client", lambda _base_url, action: action(FakeClient()))

    def fake_download_for_courses(**kwargs):
        capture.update(kwargs)
        return 0

    monkeypatch.setattr("canvasctl.cli._download_for_courses", fake_download_for_courses)

    result = runner.invoke(app, ["download", "run", "--course", "1631791"])

    assert result.exit_code == 0
    assert capture["course_paths"] == {"1631791": str(course_dest)}


def test_config_set_course_path_command(monkeypatch, tmp_path):
    from canvasctl import config

    monkeypatch.setattr(config, "config_dir", lambda: Path(tmp_path))
    config.save_config(AppConfig())

    runner = CliRunner()
    result = runner.invoke(app, ["config", "set-course-path", "1631791", str(tmp_path / "my-class")])

    assert result.exit_code == 0
    assert "Saved course path for 1631791" in result.output

    loaded = config.load_config()
    assert loaded.course_paths is not None
    assert "1631791" in loaded.course_paths


def test_config_clear_course_path_command(monkeypatch, tmp_path):
    from canvasctl import config

    monkeypatch.setattr(config, "config_dir", lambda: Path(tmp_path))
    config.save_config(AppConfig())
    config.set_course_path(1631791, tmp_path / "my-class")

    runner = CliRunner()
    result = runner.invoke(app, ["config", "clear-course-path", "1631791"])

    assert result.exit_code == 0
    assert "Cleared course path for 1631791" in result.output

    loaded = config.load_config()
    assert loaded.course_paths is None


def test_config_show_course_paths_command(monkeypatch, tmp_path):
    from canvasctl import config

    monkeypatch.setattr(config, "config_dir", lambda: Path(tmp_path))
    config.save_config(AppConfig(course_paths={"1631791": "/tmp/my-class"}))

    runner = CliRunner()
    result = runner.invoke(app, ["config", "show-course-paths"])

    assert result.exit_code == 0
    assert "1631791" in result.output
    assert "/tmp/my-class" in result.output


def test_config_show_course_paths_empty(monkeypatch, tmp_path):
    from canvasctl import config

    monkeypatch.setattr(config, "config_dir", lambda: Path(tmp_path))
    config.save_config(AppConfig())

    runner = CliRunner()
    result = runner.invoke(app, ["config", "show-course-paths"])

    assert result.exit_code == 0
    assert "No course paths configured." in result.output


def test_download_interactive_fails_when_no_valid_courses_selected(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr("canvasctl.cli._load_config_or_fail", lambda: AppConfig(base_url="https://canvas.test"))
    monkeypatch.setattr("canvasctl.cli._resolve_base_url_or_fail", lambda _cfg, _override: "https://canvas.test")

    class InteractiveClient:
        def list_courses(self, *, include_all: bool):
            assert include_all is False
            return [
                CourseSummary(
                    id=1631791,
                    course_code="MSDS-697-01",
                    name="Distributed Data Systems",
                    workflow_state="available",
                    term_name="Spring 2026",
                    start_at=None,
                    end_at=None,
                )
            ]

    monkeypatch.setattr(
        "canvasctl.cli._run_with_client",
        lambda _base_url, action: action(InteractiveClient()),
    )
    monkeypatch.setattr(
        "canvasctl.cli.prompt_interactive_selection",
        lambda _courses: InteractiveSelection(course_ids=[9999999], sources=["files"]),
    )

    result = runner.invoke(app, ["download", "interactive"])

    assert result.exit_code == 1
    assert "No valid courses selected." in result.output
