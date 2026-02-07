from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import platformdirs
import tomllib
import tomli_w

APP_NAME = "canvasctl"
DEFAULT_CONCURRENCY = 12


class ConfigError(ValueError):
    """Raised when config values are invalid."""


@dataclass(slots=True)
class AppConfig:
    base_url: str | None = None
    default_dest: str | None = None
    default_concurrency: int = DEFAULT_CONCURRENCY

    def destination_path(self, cwd: Path | None = None) -> Path:
        if self.default_dest:
            return Path(self.default_dest).expanduser()
        working_dir = cwd if cwd is not None else Path.cwd()
        return working_dir / "downloads"


def config_dir() -> Path:
    return Path(platformdirs.user_config_dir(APP_NAME))


def config_path() -> Path:
    return config_dir() / "config.toml"


def validate_base_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(f"Invalid Canvas base URL: {url!r}")

    normalized = url.strip().rstrip("/")
    if normalized.endswith("/api/v1"):
        normalized = normalized[: -len("/api/v1")]

    return normalized


def normalize_destination_path(path: str | Path) -> str:
    if isinstance(path, Path):
        path_obj = path
    elif isinstance(path, str):
        if not path.strip():
            raise ConfigError("Download path cannot be empty.")
        path_obj = Path(path)
    else:
        raise ConfigError("Download path must be a string or path.")

    try:
        return str(path_obj.expanduser().resolve())
    except OSError as exc:
        raise ConfigError(f"Invalid download path {path_obj!s}: {exc}") from exc


def _read_raw_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Could not parse config file at {path}: {exc}") from exc


def load_config() -> AppConfig:
    raw = _read_raw_config()
    base_url = raw.get("base_url")
    default_dest = raw.get("default_dest")
    default_concurrency = raw.get("default_concurrency", DEFAULT_CONCURRENCY)

    if base_url is not None:
        if not isinstance(base_url, str):
            raise ConfigError("Config key 'base_url' must be a string.")
        base_url = validate_base_url(base_url)

    if default_dest is not None:
        if not isinstance(default_dest, str):
            raise ConfigError("Config key 'default_dest' must be a string.")
        if not default_dest.strip():
            raise ConfigError("Config key 'default_dest' must not be empty.")

    if not isinstance(default_concurrency, int) or default_concurrency <= 0:
        raise ConfigError("Config key 'default_concurrency' must be a positive integer.")

    return AppConfig(
        base_url=base_url,
        default_dest=default_dest,
        default_concurrency=default_concurrency,
    )


def save_config(config: AppConfig) -> None:
    config_dir().mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "default_concurrency": config.default_concurrency,
    }
    if config.base_url is not None:
        payload["base_url"] = config.base_url
    if config.default_dest is not None:
        payload["default_dest"] = config.default_dest
    config_path().write_text(tomli_w.dumps(payload), encoding="utf-8")


def set_base_url(url: str) -> AppConfig:
    cfg = load_config()
    cfg.base_url = validate_base_url(url)
    save_config(cfg)
    return cfg


def set_default_destination(path: str | Path) -> AppConfig:
    cfg = load_config()
    cfg.default_dest = normalize_destination_path(path)
    save_config(cfg)
    return cfg


def clear_default_destination() -> AppConfig:
    cfg = load_config()
    cfg.default_dest = None
    save_config(cfg)
    return cfg


def resolve_base_url(base_url_override: str | None, cfg: AppConfig) -> str:
    if base_url_override:
        return validate_base_url(base_url_override)
    if cfg.base_url:
        return cfg.base_url
    raise ConfigError(
        "Canvas base URL is required. Use --base-url or run 'canvasctl config set-base-url <url>'."
    )
