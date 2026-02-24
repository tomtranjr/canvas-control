# CLAUDE.md

This file provides guidance to AI assistants working on the canvas-control codebase.

## Project Overview

`canvas-control` is a Canvas LMS CLI and MCP server. It provides:
- A command-line tool (`cvsctl`) for downloading course files, viewing grades, and submitting assignments
- An MCP (Model Context Protocol) server (`cvsctl-mcp`) for AI assistant integration (Claude Desktop, Cursor, Claude Code)

**Package name**: `canvasctl` (import path) / `canvas-control` (PyPI name)
**CLI entry point**: `cvsctl`
**MCP entry point**: `cvsctl-mcp`

## Repository Layout

```
canvas-control/
├── pyproject.toml              # Project config, dependencies, entry points
├── uv.lock                     # Locked dependency versions
├── README.md                   # User-facing documentation
├── docs/
│   ├── cli-reference.md        # Full command tree and flags
│   ├── configuration.md        # Token setup and path config
│   └── guides.md               # Workflow examples and troubleshooting
├── scripts/
│   └── canvas-health-check.py  # Standalone health check utility
├── src/canvasctl/              # Main package
│   ├── __init__.py
│   ├── __main__.py             # Delegates to cli.main()
│   ├── auth.py                 # Token resolution (env var or prompt)
│   ├── canvas_api.py           # Canvas REST API client (httpx)
│   ├── cli.py                  # Typer CLI — all commands live here
│   ├── config.py               # TOML config load/save via platformdirs
│   ├── courses.py              # Course formatting/sorting helpers
│   ├── downloader.py           # Download orchestration and task planning
│   ├── grades.py               # Grade display, sorting, CSV/JSON export
│   ├── interactive.py          # questionary-based interactive TUI
│   ├── manifest.py             # Download manifest persistence
│   ├── mcp_server.py           # FastMCP server exposing Canvas tools
│   └── sources.py              # Content source extraction (files, assignments, etc.)
└── tests/
    ├── conftest.py             # Adds src/ to sys.path
    ├── test_auth.py
    ├── test_canvas_api.py
    ├── test_canvas_api_new_methods.py
    ├── test_cli_assignments.py
    ├── test_cli_config.py
    ├── test_cli_courses.py
    ├── test_cli_download.py
    ├── test_cli_grades.py
    ├── test_config.py
    ├── test_downloader.py
    ├── test_grades.py
    ├── test_live_smoke.py      # Requires real Canvas credentials (marked `live`)
    ├── test_manifest.py
    ├── test_mcp_server.py
    └── test_sources.py
```

## Development Setup

This project uses [uv](https://docs.astral.sh/uv/) for environment and dependency management. Python 3.12+ is required.

```bash
# Create virtualenv and install with dev dependencies
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e '.[dev]'
```

## Running Tests

```bash
# Run all unit tests
uv run pytest

# Run live smoke tests (requires real Canvas credentials)
export CANVAS_BASE_URL="https://your-school.instructure.com"
export CANVAS_TOKEN="your-token"
export CANVAS_TEST_COURSE_ID="12345"
uv run pytest -m live
```

Live tests are marked with `@pytest.mark.live` and are excluded from the default test run. Do not run them without real credentials.

## Key Dependencies

| Package | Purpose |
|---------|---------|
| `httpx` | Async HTTP client for Canvas REST API calls |
| `typer` | CLI framework (command definitions, help, arg parsing) |
| `rich` | Terminal output: tables, progress bars, colored text |
| `questionary` | Interactive terminal prompts (course/source selection) |
| `mcp` | Model Context Protocol server framework (FastMCP) |
| `platformdirs` | Cross-platform config directory resolution |
| `tomli-w` | Writing TOML config files (reading uses stdlib `tomllib`) |
| `pytest`, `pytest-mock`, `respx` | Testing (respx mocks httpx calls) |

## Architecture

```
CLI (Typer)          MCP Server (FastMCP)
     │                       │
     └──────────┬────────────┘
                │
         Canvas API Client
           (httpx, async)
                │
    ┌───────────┴──────────────┐
    │   Business Logic          │
    │  courses / grades /       │
    │  downloader / sources /   │
    │  manifest / interactive   │
    └───────────┬──────────────┘
                │
    Config (TOML) + Auth (env/prompt)
```

### Module Responsibilities

- **`canvas_api.py`**: All HTTP calls to Canvas REST API (`/api/v1/...`). Contains data models (`CourseSummary`, `RemoteFile`, `CourseGrade`, `AssignmentGrade`), retry logic (exponential backoff for 429/5xx), and pagination handling. `CanvasClient` is instantiated per-command with a base URL and auth token.

- **`cli.py`**: Defines the full command hierarchy using Typer sub-apps (`config_app`, `courses_app`, `download_app`, `grades_app`, `assignments_app`, `mcp_app`). Commands call into other modules; no business logic lives here directly.

- **`mcp_server.py`**: FastMCP server that exposes Canvas data as MCP tools. Each tool resolves credentials from environment variables (`CANVAS_TOKEN`, `CANVAS_BASE_URL`, `CANVAS_TIMEZONE`) and calls `CanvasClient` directly.

- **`config.py`**: Loads/saves `~/.config/canvasctl/config.toml` (via `platformdirs`). Keys: `base_url`, `default_dest`, `default_concurrency` (default 12), `course_paths` (dict of course_id → path).

- **`sources.py`**: Collects `RemoteFile` objects from all Canvas content types (files, assignments, discussions, pages, modules). `normalize_sources()` validates source names; `collect_remote_files_for_course()` is the main entry point.

- **`downloader.py`**: Plans and executes concurrent downloads. `plan_course_download_tasks()` checks manifests and determines what needs downloading. `download_tasks()` runs tasks with a progress bar. Output path uses `{dest}/{course-slug}/{folder-path}/{filename}`.

- **`manifest.py`**: Persists download state to JSON (one manifest per course). Powers idempotent skip logic across runs.

- **`grades.py`**: Formats grade data into Rich tables and exports to CSV/JSON. `sort_grades()` and `sort_assignment_grades()` use stable sort by score descending.

- **`auth.py`**: Resolves Canvas token: checks `CANVAS_TOKEN` env var first, then prompts via `getpass`. Raises `AuthError` on failure.

- **`interactive.py`**: `prompt_interactive_selection()` presents questionary checkboxes for course and source selection.

## CLI Command Reference

```
cvsctl config set-base-url <url>
cvsctl config set-download-path <path>
cvsctl config clear-download-path
cvsctl config set-course-path <course_id> <path>
cvsctl config clear-course-path <course_id>
cvsctl config show-course-paths
cvsctl config show

cvsctl courses list [--all] [--json] [--base-url <url>]

cvsctl grades summary [--all] [--detailed] [--json] [--course <id-or-code>...]
cvsctl grades export [--format csv|json] [--detailed] [--dest <path>] [--course <id-or-code>...]

cvsctl assignments submit --course <id-or-code> --assignment <id-or-name>
                          [--file <path>...] [--text <content>] [--url <url>]
                          [--json] [--base-url <url>]

cvsctl download run --course <id-or-code>... [--source <source>...]
                    [--dest <path>] [--export-dest] [--overwrite] [--force]
                    [--concurrency <n>] [--base-url <url>]
cvsctl download interactive [--dest <path>] [--export-dest] [--base-url <url>]
                             [--concurrency <n>] [--force]

cvsctl mcp serve
```

Available `--source` values: `files`, `assignments`, `discussions`, `pages`, `modules` (defaults to all).

## MCP Server Tools

The MCP server exposes these tools to AI assistants:

| Tool | Description |
|------|-------------|
| `list_courses` | List enrolled courses (active or all) |
| `get_upcoming_assignments` | Assignments due within a time window |
| `get_announcements` | Recent course announcements |
| `get_calendar_events` | Calendar events within a time window |
| `get_syllabus` | Course syllabus content |
| `get_grades_summary` | Grade overview across courses |
| `get_grades_detailed` | Per-assignment grade breakdown |
| `list_course_files` | List all files in a course |
| `download_file` | Download a single file by ID |
| `complete_assignment` | Mark assignment complete |
| `sync_course_files` | Sync all course files to local disk |

MCP server credentials come from environment variables: `CANVAS_TOKEN`, `CANVAS_BASE_URL`, `CANVAS_TIMEZONE`.

## Conventions and Patterns

### Code Style

- Python 3.12+ with `from __future__ import annotations` in every module
- Full type hints throughout
- Dataclasses with `slots=True` for data models (memory efficiency)
- Immutable data models: `CourseSummary`, `RemoteFile`, `CourseGrade`, `AssignmentGrade`

### Naming

- CLI commands: hyphen-separated (`set-base-url`, `download run`)
- Python files and functions: `snake_case`
- Course slug format: `{slugified-name}-{course-id}` (e.g., `biology-12345`)
- File path segments: sanitized to remove special characters, spaces → underscores

### Error Handling

- Custom exception hierarchy: `CanvasApiError` (base) → `CanvasUnauthorizedError`
- HTTP retries with exponential backoff for 429, 500, 502, 503, 504
- `Retry-After` header honored for rate limiting
- CLI commands print user-friendly errors and exit with non-zero code

### Adding a New CLI Command

1. Define the command function in `cli.py` with Typer decorators
2. Add it to the appropriate sub-app (`config_app`, `courses_app`, etc.)
3. Put business logic in a dedicated module, not in `cli.py`
4. Add a test in `tests/test_cli_<group>.py` using `typer.testing.CliRunner` and `respx` for API mocking

### Adding a New MCP Tool

1. Add the tool function in `mcp_server.py` with `@mcp.tool()` decorator
2. Resolve credentials from env vars at the top of the function
3. Instantiate `CanvasClient` and call the appropriate API method
4. Add a test in `tests/test_mcp_server.py`

### Adding a New Canvas API Method

1. Add the method to `CanvasClient` in `canvas_api.py`
2. Use `self._get()` / `self._paginate()` for HTTP calls — do not call `httpx` directly
3. Return typed dataclass instances
4. Add a test in `tests/test_canvas_api.py` or `tests/test_canvas_api_new_methods.py` using `respx`

### Testing Patterns

- Use `respx.mock` to intercept httpx calls; never make real HTTP calls in unit tests
- CLI tests use `typer.testing.CliRunner` with `invoke(app, [...])`
- Patch `canvasctl.cli.resolve_token` (or `canvasctl.mcp_server.resolve_token`) to avoid auth prompts
- Live tests require `@pytest.mark.live` and real env vars; keep them in `test_live_smoke.py`

### Config File Location

The config file is stored at the platform-appropriate config directory:
- Linux: `~/.config/canvasctl/config.toml`
- macOS: `~/Library/Application Support/canvasctl/config.toml`

### Download Output Structure

Files are saved to: `{dest}/{course-slug}/{canvas-folder-path}/{filename}`

Duplicate filenames within a course folder get `_{file_id}` appended to avoid collisions. The manifest file is written alongside downloads for idempotent skip logic.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `CANVAS_TOKEN` | Yes (or prompted) | Canvas API access token |
| `CANVAS_BASE_URL` | For MCP server | Canvas instance URL (e.g., `https://school.instructure.com`) |
| `CANVAS_TIMEZONE` | No | Timezone for MCP server date display (e.g., `America/Los_Angeles`) |
| `CANVAS_TEST_COURSE_ID` | For live tests | Course ID used by live smoke tests |
