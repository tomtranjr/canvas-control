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


def test_destination_path_defaults_to_home_downloads():
    cfg = config.AppConfig()
    assert cfg.destination_path() == Path.home() / "Downloads"


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


def test_course_paths_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_dir", lambda: Path(tmp_path))

    cfg = config.AppConfig(
        base_url="https://school.example.edu",
        default_concurrency=12,
        course_paths={"1631791": str(tmp_path / "MSDS-697"), "2000000": str(tmp_path / "MSDS-610")},
    )
    config.save_config(cfg)

    loaded = config.load_config()
    assert loaded.course_paths is not None
    assert loaded.course_paths["1631791"] == str(tmp_path / "MSDS-697")
    assert loaded.course_paths["2000000"] == str(tmp_path / "MSDS-610")


def test_set_course_path_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_dir", lambda: Path(tmp_path))
    config.save_config(config.AppConfig())

    cfg = config.set_course_path(1631791, tmp_path / "my-class")

    assert cfg.course_paths is not None
    assert cfg.course_paths["1631791"] == str((tmp_path / "my-class").resolve())

    loaded = config.load_config()
    assert loaded.course_paths is not None
    assert loaded.course_paths["1631791"] == str((tmp_path / "my-class").resolve())


def test_clear_course_path_removes_mapping(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_dir", lambda: Path(tmp_path))
    config.save_config(config.AppConfig())

    config.set_course_path(1631791, tmp_path / "my-class")
    cfg = config.clear_course_path(1631791)

    assert cfg.course_paths is None

    loaded = config.load_config()
    assert loaded.course_paths is None


def test_get_course_path_returns_none_for_unmapped():
    cfg = config.AppConfig(course_paths={"1631791": "/some/path"})
    assert config.get_course_path(9999, cfg) is None
    assert config.get_course_path(1631791, cfg) == Path("/some/path")

    empty_cfg = config.AppConfig()
    assert config.get_course_path(1631791, empty_cfg) is None


def test_save_config_omits_empty_course_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_dir", lambda: Path(tmp_path))

    cfg = config.AppConfig(
        base_url="https://usfca.instructure.com",
        default_concurrency=12,
        course_paths=None,
    )
    config.save_config(cfg)

    text = config.config_path().read_text(encoding="utf-8")
    assert "course_paths" not in text


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
