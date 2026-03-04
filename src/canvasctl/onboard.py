from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from rich.console import Console
from rich.table import Table

from canvasctl.canvas_api import (
    CanvasApiError,
    CanvasClient,
    CanvasUnauthorizedError,
    CourseSummary,
)
from canvasctl.config import (
    AppConfig,
    ConfigError,
    load_config,
    set_base_url,
    set_course_path,
    set_default_destination,
    validate_base_url,
)
from canvasctl.courses import render_courses_table, sort_courses
from canvasctl.downloader import build_course_slug

_TOTAL_STEPS = 5


@dataclass(slots=True)
class OnboardResult:
    base_url: str | None = None
    token_source: Literal["env", "prompt", "skipped"] = "skipped"
    courses_count: int = 0
    path_strategy: Literal["single", "per_course", "default", "skipped"] = "skipped"
    default_dest: str | None = None
    per_course_paths: dict[str, str] = field(default_factory=dict)


def _load_questionary() -> Any:
    try:
        import questionary
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Onboarding requires questionary. Install project dependencies first."
        ) from exc
    return questionary


def _step_header(console: Console, step: int, title: str) -> None:
    console.print(f"\n[bold cyan][{step}/{_TOTAL_STEPS}] {title}[/bold cyan]")


def run_onboard(console: Console) -> None:
    """Interactive setup wizard for new users."""
    console.print()
    console.rule("[bold cyan]Welcome to cvsctl — Canvas LMS CLI[/bold cyan]")
    console.print(
        "\nThis wizard will configure [bold]cvsctl[/bold] — your CLI for downloading course files,\n"
        "viewing grades, and submitting assignments on Canvas LMS.\n"
        "\nYou can re-run [bold]cvsctl onboard[/bold] at any time to update these settings.\n"
    )

    try:
        cfg = load_config()
    except ConfigError as exc:
        console.print(
            f"  [yellow]Warning: existing config has an issue ({exc}). "
            "Starting with defaults.[/yellow]"
        )
        cfg = AppConfig()
    result = OnboardResult()
    client: CanvasClient | None = None

    try:
        cfg = _step_base_url(console, cfg, result)

        if cfg.base_url is None:
            console.print(
                "\n[yellow]No Canvas URL configured — skipping token, courses, and path setup.[/yellow]"
            )
        else:
            client = _step_token_and_verify(console, cfg.base_url, result)

            if client is not None:
                courses = _step_show_courses(console, client, result)
                cfg = _step_download_paths(console, cfg, courses, result)

        _step_summary(console, result)
        _print_next_steps(console)

    finally:
        if client is not None:
            client.close()


def _validate_url_inline(value: str) -> bool | str:
    """Inline validator for questionary.text — returns True on valid, error string on invalid."""
    if not value.strip():
        return True  # empty input is handled as "skip" after the prompt returns
    try:
        validate_base_url(value.strip())
        return True
    except ConfigError as exc:
        return str(exc)


def _step_base_url(console: Console, cfg: AppConfig, result: OnboardResult) -> AppConfig:
    """[1/5] Confirm or set Canvas base URL."""
    _step_header(console, 1, "Canvas URL")
    questionary = _load_questionary()

    if cfg.base_url:
        console.print(f"  Current URL: [cyan]{cfg.base_url}[/cyan]")
        keep = questionary.confirm("  Keep this URL?", default=True).ask()
        if keep is None:
            raise KeyboardInterrupt
        if keep:
            result.base_url = cfg.base_url
            console.print("  [green]✓ Keeping current URL.[/green]")
            return cfg

    url = questionary.text(
        "  Enter your Canvas URL (e.g. https://school.instructure.com):",
        validate=_validate_url_inline,
    ).ask()

    if url is None:
        raise KeyboardInterrupt

    url = url.strip()
    if not url:
        console.print("  [yellow]No URL entered — skipping.[/yellow]")
        return cfg

    try:
        cfg = set_base_url(url)
        result.base_url = cfg.base_url
        console.print(f"  [green]✓ Saved:[/green] {cfg.base_url}")
    except ConfigError as exc:
        console.print(f"  [red]Invalid URL: {exc}[/red]")
    except OSError as exc:
        console.print(
            f"  [red]Could not save configuration: {exc}[/red]\n"
            "  Check that the config directory is writable."
        )

    return cfg


def _step_token_and_verify(
    console: Console, base_url: str, result: OnboardResult
) -> CanvasClient | None:
    """[2/5] Collect token (env or prompt), verify with the Canvas API.

    Returns an open CanvasClient on success, None if skipped or all retries failed.
    Caller is responsible for closing the returned client.
    """
    _step_header(console, 2, "Canvas API Token")
    questionary = _load_questionary()

    env_token = os.environ.get("CANVAS_TOKEN", "").strip()
    token: str | None = None

    if env_token:
        console.print("  [green]✓ Found CANVAS_TOKEN in environment.[/green]")
        use_env = questionary.confirm("  Use this token?", default=True).ask()
        if use_env is None:
            raise KeyboardInterrupt
        if use_env:
            token = env_token
            result.token_source = "env"

    if token is None:
        console.print(
            f"\n  To create a Canvas API token:\n"
            f"  1. Open  {base_url}/profile/settings\n"
            f"  2. Scroll to [bold]Approved Integrations[/bold]\n"
            f"  3. Click [bold]+ New Access Token[/bold]\n"
        )
        raw = questionary.password("  Canvas API token:").ask()
        if raw is None:
            raise KeyboardInterrupt
        token = raw.strip()
        if not token:
            console.print("  [yellow]No token entered — skipping verification.[/yellow]")
            return None
        result.token_source = "prompt"

    for attempt in range(1, 4):
        client = CanvasClient(base_url, token)
        try:
            client.list_courses(include_all=False)
            console.print("  [green]✓ Token verified successfully.[/green]")
            return client
        except CanvasUnauthorizedError:
            client.close()
            console.print(f"  [red]✗ Invalid token (attempt {attempt}/3).[/red]")
            if attempt < 3:
                retry = questionary.confirm("  Try a different token?", default=True).ask()
                if retry is None or not retry:
                    console.print("  [yellow]Skipping token verification.[/yellow]")
                    return None
                raw = questionary.password("  Canvas API token:").ask()
                if raw is None:
                    raise KeyboardInterrupt
                token = raw.strip()
                if not token:
                    console.print("  [yellow]No token entered — skipping.[/yellow]")
                    return None
                result.token_source = "prompt"
            else:
                console.print("  [yellow]Too many failed attempts — skipping.[/yellow]")
                return None
        except CanvasApiError as exc:
            client.close()
            if "403" in str(exc):
                console.print(
                    f"  [red]Canvas denied the request: {exc}[/red]\n"
                    "  Your token may lack the required permissions."
                )
            else:
                console.print(
                    f"  [red]Cannot reach Canvas ({exc}) — check URL and network.[/red]"
                )
            retry = questionary.confirm("  Retry?", default=False).ask()
            if retry is None or not retry:
                return None
            raw = questionary.password("  Canvas API token:").ask()
            if raw is None:
                raise KeyboardInterrupt
            token = raw.strip()
            if not token:
                return None
            result.token_source = "prompt"

    return None


def _step_show_courses(
    console: Console, client: CanvasClient, result: OnboardResult
) -> list[CourseSummary]:
    """[3/5] Fetch and display the active courses table."""
    _step_header(console, 3, "Your Courses")
    try:
        courses = sort_courses(client.list_courses(include_all=False))
    except CanvasApiError as exc:
        console.print(
            f"  [red]Could not fetch courses: {exc}[/red]\n"
            "  Check your network connection or try again later."
        )
        return []
    result.courses_count = len(courses)
    if not courses:
        console.print("  [yellow]No active courses found.[/yellow]")
    else:
        console.print(render_courses_table(courses))
    return courses


def _step_download_paths(
    console: Console, cfg: AppConfig, courses: list[CourseSummary], result: OnboardResult
) -> AppConfig:
    """[4/5] Configure download paths (single / per-course / default / skip)."""
    _step_header(console, 4, "Download Paths")
    questionary = _load_questionary()

    console.print(
        "  Configure where course files are saved when you run [bold]cvsctl download[/bold].\n"
    )

    choice = questionary.select(
        "  Download path setup:",
        choices=[
            questionary.Choice(
                title="Single folder — all courses save to one folder",
                value="single",
            ),
            questionary.Choice(
                title="Per-course folders — set a different path for each course",
                value="per_course",
            ),
            questionary.Choice(
                title="Use defaults (~/Downloads)",
                value="default",
            ),
            questionary.Choice(
                title="Skip — configure later with 'cvsctl config set-download-path'",
                value="skip",
            ),
        ],
    ).ask()

    if choice is None:
        raise KeyboardInterrupt

    if choice == "single":
        cfg = _configure_single_path(console, questionary, cfg, result)

    elif choice == "per_course":
        cfg = _configure_per_course_paths(console, questionary, cfg, courses, result)

    elif choice == "default":
        result.path_strategy = "default"
        console.print("  [green]✓ Using default:[/green] ~/Downloads")

    else:  # skip
        result.path_strategy = "skipped"
        console.print(
            "  [yellow]Skipped.[/yellow] Run 'cvsctl config set-download-path <path>' later."
        )

    return cfg


def _configure_single_path(
    console: Console, questionary: Any, cfg: AppConfig, result: OnboardResult
) -> AppConfig:
    default_path = str(Path.home() / "Downloads")
    path = questionary.text(
        "  Download folder path:",
        default=default_path,
    ).ask()
    if path is None:
        raise KeyboardInterrupt
    path = path.strip() or default_path
    try:
        cfg = set_default_destination(path)
        result.path_strategy = "single"
        result.default_dest = cfg.default_dest
        console.print(f"  [green]✓ Saved:[/green] {cfg.default_dest}")
    except ConfigError as exc:
        console.print(f"  [red]Invalid path: {exc}[/red]")
    except OSError as exc:
        console.print(
            f"  [red]Could not save configuration: {exc}[/red]\n"
            "  Check that the config directory is writable."
        )
    return cfg


def _configure_per_course_paths(
    console: Console,
    questionary: Any,
    cfg: AppConfig,
    courses: list[CourseSummary],
    result: OnboardResult,
) -> AppConfig:
    if not courses:
        console.print("  [yellow]No courses available to configure paths for.[/yellow]")
        return cfg

    course_choices = [
        questionary.Choice(
            title=f"{c.course_code or '[no-code]'} | {c.name}",
            value=c,
            checked=True,
        )
        for c in courses
    ]
    selected = questionary.checkbox(
        "  Select courses to configure paths for (Space to toggle, Enter to confirm):",
        choices=course_choices,
    ).ask()

    if selected is None:
        raise KeyboardInterrupt

    for course in selected:
        slug = build_course_slug(course)
        default_path = str(Path.home() / "Downloads" / slug)
        label = course.course_code or course.name
        path = questionary.text(
            f"  Path for {label} (blank to skip):",
            default=default_path,
        ).ask()
        if path is None:
            raise KeyboardInterrupt
        path = path.strip()
        if not path:
            continue
        try:
            set_course_path(course.id, path)
            result.per_course_paths[str(course.id)] = path
            result.path_strategy = "per_course"
            console.print(f"  [green]✓[/green] {label}: {path}")
        except (ConfigError, OSError) as exc:
            console.print(f"  [red]Invalid path for {course.name}: {exc}[/red]")

    return cfg


def _step_summary(console: Console, result: OnboardResult) -> None:
    """[5/5] Print a summary table of everything that was configured."""
    _step_header(console, 5, "Setup Complete!")
    console.print()

    table = Table(title="Configuration Summary", show_header=True)
    table.add_column("Setting", style="bold")
    table.add_column("Value")

    table.add_row("Canvas URL", result.base_url or "[dim]not set[/dim]")

    token_desc = {
        "env": "[green]from CANVAS_TOKEN env var[/green]",
        "prompt": "[yellow]entered manually (not stored)[/yellow]",
        "skipped": "[dim]not configured[/dim]",
    }.get(result.token_source, result.token_source)
    table.add_row("Token", token_desc)

    table.add_row(
        "Courses found",
        str(result.courses_count) if result.courses_count else "[dim]—[/dim]",
    )

    path_desc: str
    if result.path_strategy == "single":
        path_desc = f"Single folder: {result.default_dest}"
    elif result.path_strategy == "per_course":
        path_desc = f"Per-course ({len(result.per_course_paths)} configured)"
    elif result.path_strategy == "default":
        path_desc = "~/Downloads (default)"
    else:
        path_desc = "[dim]not configured[/dim]"
    table.add_row("Download paths", path_desc)

    console.print(table)

    if result.token_source == "prompt":
        console.print(
            "\n[yellow]Tip:[/yellow] To avoid re-entering your token on every run, "
            "add this to your shell profile (~/.bashrc, ~/.zshrc, etc.):\n"
            "  [bold]export CANVAS_TOKEN=<your-token>[/bold]\n"
        )


def _print_next_steps(console: Console) -> None:
    console.rule("[bold]Next Steps[/bold]")
    console.print()
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Command", style="bold cyan", no_wrap=True)
    table.add_column("Description")
    table.add_row("cvsctl courses list", "See all your enrolled courses")
    table.add_row("cvsctl grades summary", "View grades across courses")
    table.add_row("cvsctl download interactive", "Download course files interactively")
    table.add_row("cvsctl download run --course <id>", "Download files for a specific course")
    table.add_row("cvsctl --help", "Explore all available commands")
    console.print(table)
    console.print()
