# Scripts

Optional utilities that use canvasctl. Install the project first: `uv pip install -e .`

## canvas-health-check.py

Verifies that your Canvas base URL and API token work by calling the Canvas API (current user profile). Useful before running downloads or after changing config/token.

```bash
# Use configured base URL and CANVAS_TOKEN (or prompt for token)
python scripts/canvas-health-check.py

# Override base URL
python scripts/canvas-health-check.py --base-url https://your-school.instructure.com
```

Exit code 0 on success, 1 on config/auth/API failure.
