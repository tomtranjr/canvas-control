from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from canvasctl import config
from canvasctl.cli import app


def test_config_set_download_path_persists(monkeypatch, tmp_path):
    runner = CliRunner()
    monkeypatch.setattr(config, "config_dir", lambda: Path(tmp_path))

    destination = tmp_path / "my-downloads"
    result = runner.invoke(app, ["config", "set-download-path", str(destination)])

    assert result.exit_code == 0
    assert "Saved default download path" in result.output
    loaded = config.load_config()
    assert loaded.default_dest == str(destination.resolve())


def test_config_clear_download_path(monkeypatch, tmp_path):
    runner = CliRunner()
    monkeypatch.setattr(config, "config_dir", lambda: Path(tmp_path))
    config.set_default_destination(tmp_path / "persisted")

    result = runner.invoke(app, ["config", "clear-download-path"])

    assert result.exit_code == 0
    assert "Cleared default download path" in result.output
    loaded = config.load_config()
    assert loaded.default_dest is None


def test_config_show_includes_effective_dest(monkeypatch):
    runner = CliRunner()
    configured = Path("/tmp/canvasctl-dest")

    monkeypatch.setattr(
        "canvasctl.cli._load_config_or_fail",
        lambda: config.AppConfig(
            base_url="https://canvas.test",
            default_dest=str(configured),
            default_concurrency=12,
        ),
    )

    result = runner.invoke(app, ["config", "show"])

    assert result.exit_code == 0
    assert "effective_dest" in result.output
    assert str(configured.resolve()) in result.output
