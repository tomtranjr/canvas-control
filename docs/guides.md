# Guides

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

## Viewing grades

Check your current grades across all active courses:

```bash
cvsctl grades summary
```

This prints a table with course name, letter grade, and percentage for each course.

Include concluded/past courses:

```bash
cvsctl grades summary --all
```

See a per-assignment breakdown (scores, possible points, status):

```bash
cvsctl grades summary --detailed
```

Filter to specific courses:

```bash
cvsctl grades summary --course 12345 --course BIO101
```

Output as JSON (useful for scripting):

```bash
cvsctl grades summary --json
```

Combine flags:

```bash
cvsctl grades summary --detailed --json --course 12345
```

## Exporting grades

Export your grades to a file for offline analysis or tracking:

```bash
cvsctl grades export
```

By default, this creates a CSV file at `~/Downloads/canvasctl-grades.csv`.

Export as JSON instead:

```bash
cvsctl grades export --format json
```

Include per-assignment detail:

```bash
cvsctl grades export --detailed
```

Choose a custom download location:

```bash
cvsctl grades export --dest ~/Desktop/reports
```

Filter to specific courses:

```bash
cvsctl grades export --course 12345 --course BIO101
```

Combine flags:

```bash
cvsctl grades export --detailed --format json --dest ~/Desktop --course 12345
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

## Health check

Use the health check before your first download, after rotating credentials, or when you suspect auth/config issues:

```bash
python scripts/canvas-health-check.py
```

This check validates:

- your effective Canvas base URL (config or override)
- your resolved token source (`CANVAS_TOKEN` or prompt flow)
- successful auth by calling `users/self/profile`
- the identity Canvas returns for the token

Override the base URL with:

```bash
python scripts/canvas-health-check.py --base-url https://your-school.instructure.com
```

Exit code 0 on success, 1 on config/auth/API failure.

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

Grades show N/A:

- verify you are enrolled as a student in the course
- some courses may not publish grades until the term ends
- use `--all` to include concluded courses
