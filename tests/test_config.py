from __future__ import annotations

from pathlib import Path

from canvasctl import config


def test_validate_base_url_normalizes_api_suffix():
    value = config.validate_base_url("https://example.instructure.com/api/v1")
    assert value == "https://example.instructure.com"


def test_load_save_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_dir", lambda: Path(tmp_path))

    cfg = config.AppConfig(
        base_url="https://school.example.edu",
        default_dest=str(tmp_path / "downloads"),
        default_concurrency=8,
    )
    config.save_config(cfg)

    loaded = config.load_config()
    assert loaded.base_url == "https://school.example.edu"
    assert loaded.default_concurrency == 8
    assert loaded.default_dest == str(tmp_path / "downloads")


def test_destination_path_defaults_to_downloads_under_cwd():
    cfg = config.AppConfig()
    assert cfg.destination_path(cwd=Path("/tmp/project")) == Path("/tmp/project/downloads")


def test_set_default_destination_persists_resolved_path(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_dir", lambda: Path(tmp_path))

    cfg = config.set_default_destination(Path("~/canvasctl-downloads"))

    assert cfg.default_dest is not None
    loaded = config.load_config()
    assert loaded.default_dest == cfg.default_dest
    assert str(Path(loaded.default_dest)).startswith(str(Path.home()))


def test_clear_default_destination(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_dir", lambda: Path(tmp_path))
    config.set_default_destination(tmp_path / "saved-dest")

    cfg = config.clear_default_destination()

    assert cfg.default_dest is None
    loaded = config.load_config()
    assert loaded.default_dest is None


def test_resolve_base_url_requires_value(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_dir", lambda: Path(tmp_path))
    cfg = config.load_config()

    try:
        config.resolve_base_url(None, cfg)
    except config.ConfigError as exc:
        assert "base URL" in str(exc)
    else:
        raise AssertionError("Expected ConfigError for missing base URL")


def test_save_config_omits_none_values(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_dir", lambda: Path(tmp_path))

    cfg = config.AppConfig(
        base_url="https://usfca.instructure.com",
        default_dest=None,
        default_concurrency=12,
    )
    config.save_config(cfg)

    text = config.config_path().read_text(encoding="utf-8")
    assert "default_dest" not in text


def test_load_config_rejects_empty_default_dest(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_dir", lambda: Path(tmp_path))

    config.config_dir().mkdir(parents=True, exist_ok=True)
    config.config_path().write_text(
        'default_concurrency = 12\ndefault_dest = ""\n',
        encoding="utf-8",
    )

    try:
        config.load_config()
    except config.ConfigError as exc:
        assert "default_dest" in str(exc)
    else:
        raise AssertionError("Expected ConfigError for empty default_dest")
