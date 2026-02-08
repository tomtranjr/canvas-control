# canvas-control

`canvas-control` turns Canvas into a fast, scriptable download pipeline.

Instead of clicking through files one-by-one, you can:

- list your courses in seconds
- pull files from multiple Canvas content sources in one run
- use interactive prompts when you want guidance
- generate manifests so failed downloads can be resumed

## Why canvas-control is powerful

- One command can download from `files`, `assignments`, `discussions`, `pages`, and `modules`.
- It is built for repeatable workflows: predictable output paths and machine-readable manifests.
- It works for both beginners and power users: guided mode (`download interactive`) and fully scripted mode (`download run`).
- It handles real-world interruptions: failed/pending items can be resumed from a manifest.

## Quick start

`canvas-control` uses [uv](https://docs.astral.sh/uv/) for environment and dependency management.

1. Create and activate a virtual environment (Python 3.12+):

```bash
uv venv --python 3.12
source .venv/bin/activate
```

2. Install the project and dev dependencies:

```bash
uv pip install -e '.[dev]'
```

3. Set your Canvas base URL once:

```bash
cvsctl config set-base-url https://your-school.instructure.com
```

4. Set `CANVAS_TOKEN` (recommended) or let `cvsctl` prompt for it.

5. Run your first command:

```bash
cvsctl courses list
```

## Set `CANVAS_TOKEN`

Create a token in Canvas:

1. Log in to Canvas.
2. Go to `Account` -> `Settings`.
3. Under approved integrations / access tokens, create a **New Access Token**.
4. Copy the token value.

Set it in your shell:

```bash
export CANVAS_TOKEN="your-token"
```

Tips so you do not copy/paste every time:

- Add the export to your shell profile (`~/.zshrc` or `~/.bashrc`) and restart your shell.
- If you use `direnv`, put `export CANVAS_TOKEN="..."` in a project `.envrc` and run `direnv allow`.
- If a token rotates, update the saved value once in your profile (or `.envrc`).

## First real workflow

List courses, then download one by ID:

```bash
cvsctl courses list
cvsctl download run --course 12345
```

Download two courses in one command:

```bash
cvsctl download run --course 12345 --course 67890
```

Limit sources to just files + assignments:

```bash
cvsctl download run --course 12345 --source files --source assignments
```

Overwrite existing files:

```bash
cvsctl download run --course 12345 --overwrite true
```

## Configuration deep-dive

`canvas-control` has two destination concepts:

- `default_dest`: saved path in config
- `effective_dest`: active path for this run

If no destination is configured, downloads default to `./downloads`.

Show current config:

```bash
cvsctl config show
```

Set a persistent default download location:

```bash
cvsctl config set-download-path ~/Downloads/canvas-files
```

Clear the persistent default:

```bash
cvsctl config clear-download-path
```

Use a one-off destination without saving it:

```bash
cvsctl download run --course 12345 --dest ~/Desktop/tmp-canvas
```

Use and save a destination in one step:

```bash
cvsctl download run --course 12345 --dest ~/Downloads/canvas-files --export-dest
```

## Interactive mode

If you want a guided flow (choose courses, sources, and possibly file-level selection), use:

```bash
cvsctl download interactive
```

You can still provide overrides:

```bash
cvsctl download interactive --dest ~/Downloads/canvas-files --export-dest --concurrency 16
```

## Resume failed downloads

Every run writes manifest files. To retry anything marked `failed` or `pending`:

```bash
cvsctl download resume --manifest /path/to/.canvasctl-runs/<run-id>.json
```

This is ideal for flaky networks or large course downloads.

## Command reference

Current command tree:

- `cvsctl config set-base-url <url>`
- `cvsctl config set-download-path <path>`
- `cvsctl config clear-download-path`
- `cvsctl config show`
- `cvsctl courses list [--all] [--json] [--base-url <url>]`
- `cvsctl download run --course <id-or-code>... [--source <source>...] [--dest <path>] [--export-dest] [--overwrite <bool>] [--force] [--concurrency <n>] [--base-url <url>]`
- `cvsctl download interactive [--dest <path>] [--export-dest] [--base-url <url>] [--concurrency <n>] [--force]`
- `cvsctl download resume --manifest <path>`

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
- or unset it and let `cvsctl` prompt you again

No base URL configured:

- run `cvsctl config set-base-url https://your-school.instructure.com`

No files downloaded:

- check source filters (`--source`)
- run `cvsctl courses list --all` to verify course visibility/state
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
