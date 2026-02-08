#!/usr/bin/env python3
"""
Canvas connectivity health check.

Uses canvas-control config, auth, and API client to verify that the configured
Canvas base URL and token work. Does not modify any canvas-control state.
Run from project root after installing canvas-control (e.g. uv pip install -e .):

    python scripts/canvas-health-check.py
    python scripts/canvas-health-check.py --base-url https://your-school.instructure.com

Exit code 0 on success, 1 on failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow importing canvasctl when run from repo root (e.g. uv run python scripts/...)
if __name__ == "__main__":
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from rich.console import Console
from rich.table import Table

from canvasctl.auth import AuthError, resolve_token
from canvasctl.canvas_api import (
    CanvasApiError,
    CanvasClient,
    CanvasUnauthorizedError,
)
from canvasctl.config import ConfigError, load_config, resolve_base_url


def _run_health_check(base_url_override: str | None) -> int:
    console = Console()
    try:
        cfg = load_config()
    except ConfigError as e:
        console.print(f"[red]Config error:[/red] {e}")
        return 1

    try:
        base_url = resolve_base_url(base_url_override, cfg)
    except ConfigError as e:
        console.print(f"[red]{e}[/red]")
        return 1

    try:
        token_info = resolve_token(console)
    except AuthError as e:
        console.print(f"[red]Auth error:[/red] {e}")
        return 1

    try:
        with CanvasClient(base_url, token_info.token, timeout=15.0) as client:
            profile = client.get_json("users/self/profile")
    except CanvasUnauthorizedError:
        console.print("[red]Canvas rejected the token (401). Check CANVAS_TOKEN or re-enter.[/red]")
        return 1
    except CanvasApiError as e:
        console.print(f"[red]API error:[/red] {e}")
        return 1

    name = profile.get("name") or "Unknown"
    login_id = profile.get("login_id") or profile.get("primary_email") or ""
    table = Table(title="Canvas health check")
    table.add_column("Check", style="cyan")
    table.add_column("Result", style="green")
    table.add_row("Base URL", base_url)
    table.add_row("Token source", token_info.source)
    table.add_row("Authenticated as", f"{name}" + (f" ({login_id})" if login_id else ""))
    console.print(table)
    console.print("[green]Health check passed.[/green]")
    return 0


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Verify Canvas base URL and token.")
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="Override Canvas instance URL (otherwise uses canvas-control config).",
    )
    args = parser.parse_args()
    return _run_health_check(args.base_url)


if __name__ == "__main__":
    sys.exit(main())
