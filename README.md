# canvasctl

`canvasctl` is a Python CLI for Canvas LMS that can:

- list courses
- download course files and attachment-backed assets
- run in scripted mode or interactive mode
- generate download manifests for resumable workflows

## Quick start

1. Install in editable mode:

```bash
python3 -m pip install -e '.[dev]'
```

2. Set a default Canvas URL once:

```bash
canvasctl config set-base-url https://your-school.instructure.com
```

3. List active courses:

```bash
canvasctl courses list
```

4. Download files for a course:

```bash
canvasctl download run --course 12345
```

Default behavior skips existing files. To overwrite existing filenames, use:

```bash
canvasctl download run --course 12345 --overwrite true
```

The CLI reads `CANVAS_TOKEN` if set; otherwise it prompts securely for a token.
