# canvasctl

`canvasctl` is a Python CLI for Canvas LMS that can:

- list courses
- download course files and attachment-backed assets
- run in scripted mode or interactive mode
- generate download manifests for resumable workflows

## Command reference

Current command tree:

- `canvasctl config set-base-url <url>`
- `canvasctl config set-download-path <path>`
- `canvasctl config clear-download-path`
- `canvasctl config show`
- `canvasctl courses list [--all] [--json] [--base-url <url>]`
- `canvasctl download run --course <id-or-code>... [--source <source>...] [--dest <path>] [--export-dest] [--overwrite <bool>] [--force] [--concurrency <n>] [--base-url <url>]`
- `canvasctl download interactive [--dest <path>] [--export-dest] [--base-url <url>] [--concurrency <n>] [--force]`
- `canvasctl download resume --manifest <path>`

Available values for `--source`:

- `files`
- `assignments`
- `discussions`
- `pages`
- `modules`

Notes:

- `--course` is required for `download run` and can be repeated.
- `--source` defaults to all source types when omitted.
- When no destination is configured, downloads default to `./downloads`.
- `--dest` sets destination for the current command only.
- `--export-dest` requires `--dest` and saves that path as future default.
- `canvasctl config show` displays both `default_dest` (saved value) and `effective_dest` (active path).
- `--overwrite` defaults to false (`--force` is equivalent to overwrite true).
- `--concurrency` defaults to configured `default_concurrency` (12) when omitted.
- `--manifest` is required for `download resume`.
- Every command supports `--help`.

## Quick start (using uv)

`canvasctl` requires Python 3.12+.

1. Install `uv`:

macOS (Homebrew):

```bash
brew install uv
```

Linux/macOS (official installer):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

2. Install Python 3.12 (if needed):

```bash
uv python install 3.12
```

3. Create a virtual environment in this project:

```bash
uv venv --python 3.12
```

4. Activate the virtual environment:

macOS/Linux:

```bash
source .venv/bin/activate
```

Windows (PowerShell):

```powershell
.venv\Scripts\Activate.ps1
```

5. Install this project (editable) and dev dependencies:

```bash
uv pip install -e '.[dev]'
```

6. Set a default Canvas URL once:

```bash
canvasctl config set-base-url https://your-school.instructure.com
```

7. List active courses:

```bash
canvasctl courses list
```

8. Download files for a course:

```bash
canvasctl download run --course 12345
```

Default behavior skips existing files. To overwrite existing filenames, use:

```bash
canvasctl download run --course 12345 --overwrite true
```

Use a one-off destination:

```bash
canvasctl download run --course 12345 --dest ~/Downloads/canvas-course-files
```

Persist that destination for future commands:

```bash
canvasctl download run --course 12345 --dest ~/Downloads/canvas-course-files --export-dest
```

Or set/clear it directly in config:

```bash
canvasctl config set-download-path ~/Downloads/canvas-course-files
canvasctl config show
canvasctl config clear-download-path
```

The CLI reads `CANVAS_TOKEN` if set; otherwise it prompts securely for a token.

## Contributing

Contributions are welcome. Use the workflow below to keep changes consistent and reviewable.

1. Set up your local dev environment using the Quick start section above (`uv`, Python 3.12, and `uv pip install -e '.[dev]'`).
2. Create a topic branch for your change.
3. Make focused changes with tests when behavior changes.
4. Run tests before opening a pull request:

```bash
pytest
```

5. (Optional) Run the live smoke test if you have a Canvas sandbox and credentials:

```bash
export CANVAS_BASE_URL="https://your-school.instructure.com"
export CANVAS_TOKEN="your-token"
export CANVAS_TEST_COURSE_ID="12345"
pytest -m live
```

6. Open a pull request with a clear summary of what changed, why the change is needed, and any test coverage added or updated.
