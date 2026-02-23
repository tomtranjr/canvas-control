# Configuration

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

## Download paths

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

## Per-course download paths

Map a course to a specific directory:

```bash
cvsctl config set-course-path 12345 ~/Documents/biology
```

Remove a per-course mapping:

```bash
cvsctl config clear-course-path 12345
```

Show all per-course mappings:

```bash
cvsctl config show-course-paths
```

When a per-course path is set, that course's files download directly to the mapped directory instead of a subfolder under the default destination.
