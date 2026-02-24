# CLI Reference

## Command tree

- `cvsctl config set-base-url <url>`
- `cvsctl config set-download-path <path>`
- `cvsctl config clear-download-path`
- `cvsctl config set-course-path <course_id> <path>`
- `cvsctl config clear-course-path <course_id>`
- `cvsctl config show-course-paths`
- `cvsctl config show`
- `cvsctl courses list [--all] [--json] [--base-url <url>]`
- `cvsctl grades summary [--all] [--detailed] [--json] [--course <id-or-code>...]`
- `cvsctl grades export [--format csv|json] [--detailed] [--dest <path>] [--course <id-or-code>...]`
- `cvsctl assignments submit --course <id-or-code> --assignment <id-or-name> [--file <path>...] [--text <content>] [--url <https://...>] [--json] [--base-url <url>]`
- `cvsctl download run --course <id-or-code>... [--source <source>...] [--dest <path>] [--export-dest] [--overwrite <bool>] [--force] [--concurrency <n>] [--base-url <url>]`
- `cvsctl download interactive [--dest <path>] [--export-dest] [--base-url <url>] [--concurrency <n>] [--force]`
- `cvsctl mcp serve`

## Available `--source` values

- `files`
- `assignments`
- `discussions`
- `pages`
- `modules`

## Behavior notes

- `--course` is required for `download run` and can be repeated.
- `--course` and `--assignment` are required for `assignments submit`.
- `assignments submit` requires exactly one of `--file`, `--text`, or `--url`.
- `--course` is optional for `grades summary` and `grades export` (shows all courses when omitted).
- `--source` defaults to all values when omitted.
- `--dest` affects only the current command.
- `--export-dest` requires `--dest` and persists that path.
- `--overwrite` defaults to false.
- `--force` is equivalent to overwrite true.
- `--concurrency` defaults to configured `default_concurrency` (12).
- `--format` defaults to `csv` for `grades export`.
- `--dest` for `grades export` defaults to `~/Downloads`.
- Every command supports `--help`.
