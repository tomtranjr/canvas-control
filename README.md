# canvasctl

`canvasctl` turns Canvas into a fast, scriptable download pipeline.

Instead of clicking through files one-by-one, you can:

- list your courses in seconds
- pull files from multiple Canvas content sources in one run
- use interactive prompts when you want guidance
- generate manifests so failed downloads can be resumed

## Why canvasctl is powerful

- One command can download from `files`, `assignments`, `discussions`, `pages`, and `modules`.
- It is built for repeatable workflows: predictable output paths and machine-readable manifests.
- It works for both beginners and power users: guided mode (`download interactive`) and fully scripted mode (`download run`).
- It handles real-world interruptions: failed/pending items can be resumed from a manifest.

## 5-minute quick start (uv + Python 3.12+)

1. Install `uv`.

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

2. Install Python 3.12 (if needed).

```bash
uv python install 3.12
```

3. Create and activate a virtual environment in this repo.

```bash
uv venv --python 3.12
source .venv/bin/activate
```

Windows PowerShell activation:

```powershell
.venv\Scripts\Activate.ps1
```

4. Install the project and dev dependencies.

```bash
uv pip install -e '.[dev]'
```

5. Set your Canvas URL once.

```bash
canvasctl config set-base-url https://your-school.instructure.com
```

6. Run your first command.

```bash
canvasctl courses list
```

`canvasctl` reads `CANVAS_TOKEN` automatically if you set it. If not set, it securely prompts.

## First real workflow

List courses, then download one by ID:

```bash
canvasctl courses list
canvasctl download run --course 12345
```

Download two courses in one command:

```bash
canvasctl download run --course 12345 --course 67890
```

Limit sources to just files + assignments:

```bash
canvasctl download run --course 12345 --source files --source assignments
```

Overwrite existing files:

```bash
canvasctl download run --course 12345 --overwrite true
```

## Configuration deep-dive

`canvasctl` has two destination concepts:

- `default_dest`: saved path in config
- `effective_dest`: active path for this run

If no destination is configured, downloads default to `./downloads`.

Show current config:

```bash
canvasctl config show
```

Set a persistent default download location:

```bash
canvasctl config set-download-path ~/Downloads/canvas-files
```

Clear the persistent default:

```bash
canvasctl config clear-download-path
```

Use a one-off destination without saving it:

```bash
canvasctl download run --course 12345 --dest ~/Desktop/tmp-canvas
```

Use and save a destination in one step:

```bash
canvasctl download run --course 12345 --dest ~/Downloads/canvas-files --export-dest
```

## Interactive mode

If you want a guided flow (choose courses, sources, and possibly file-level selection), use:

```bash
canvasctl download interactive
```

You can still provide overrides:

```bash
canvasctl download interactive --dest ~/Downloads/canvas-files --export-dest --concurrency 16
```

## Resume failed downloads

Every run writes manifest files. To retry anything marked `failed` or `pending`:

```bash
canvasctl download resume --manifest /path/to/.canvasctl-runs/<run-id>.json
```

This is ideal for flaky networks or large course downloads.

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

Available `--source` values:

- `files`
- `assignments`
- `discussions`
- `pages`
- `modules`

Behavior notes:

- `--course` is required for `download run` and can be repeated.
- `--source` defaults to all values when omitted.
- `--dest` affects only the current command.
- `--export-dest` requires `--dest` and persists that path.
- `--overwrite` defaults to false.
- `--force` is equivalent to overwrite true.
- `--concurrency` defaults to configured `default_concurrency` (12).
- `--manifest` is required for `download resume`.
- Every command supports `--help`.

## Troubleshooting

401 / token rejected:

- update `CANVAS_TOKEN` and retry
- or unset it and let `canvasctl` prompt you again

No base URL configured:

- run `canvasctl config set-base-url https://your-school.instructure.com`

No files downloaded:

- check source filters (`--source`)
- run `canvasctl courses list --all` to verify course visibility/state
- use `download interactive` to inspect course/file selections

## Contributing

1. Create a branch for your change.
2. Implement focused changes and tests.
3. Run tests:

```bash
uv run pytest
```

4. Optional live smoke test (requires real Canvas credentials):

```bash
export CANVAS_BASE_URL="https://your-school.instructure.com"
export CANVAS_TOKEN="your-token"
export CANVAS_TEST_COURSE_ID="12345"
uv run pytest -m live
```

5. Open a PR with what changed, why, and test coverage.
