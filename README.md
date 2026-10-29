# dev-companion

A proof of concept for an MCP (Model Context Protocol) server that wraps everyday software engineering work (git history, tests, logs, service health, CI status), plus a one-page web app that uses it.

The web app, "Why did this fail?", demonstrates three MCP features end to end:

- **Completion**: the log file input autocompletes from the server as you type.
- **Prompt**: the `explain_failure` prompt is loaded from the server, not hard-coded in the app.
- **Tools**: Claude calls the server's tools (`search_logs`, `recent_commits`, and others) and the page shows each call live.

## Project layout

```
dev-companion/
├── server.py          MCP server: tools, resources, resource templates, prompts, completion
├── app.py             FastAPI backend: MCP client + Claude tool-use loop, streams events to the page
├── index.html         The one-page UI, served by app.py at /
├── README.md          This file
├── pyproject.toml     Created during setup (uv)
├── logs/              Sample logs for local testing (created during setup)
└── tests/             Smoke tests (created during setup)
```

## Requirements

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/) for dependencies and running
- git, with the target folder being (or pointing at) a git repository
- An Anthropic API key in `ANTHROPIC_API_KEY`, needed only for the web app's diagnose step

## Configuration

All settings are environment variables. Only `ANTHROPIC_API_KEY` is required, and only for `app.py`.

| Variable | Used by | Default | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | app.py | (none) | Claude API key. Never commit it. |
| `ANTHROPIC_MODEL` | app.py | `claude-sonnet-5-5` | Model used for the diagnose loop |
| `DEV_REPO_PATH` | server.py | current directory | Git repo the tools operate on |
| `DEV_LOG_DIR` | server.py | `<repo>/logs` | Folder of log files for `search_logs` and completion |
| `DEV_SERVICES` | server.py | `{}` | JSON map of service name to health URL, e.g. `{"api":"http://localhost:8080/health"}` |
| `GITHUB_REPO` | server.py | (none) | `owner/repo`, enables `ci_status` |
| `GITHUB_TOKEN` | server.py | (none) | Token with read access to Actions, enables `ci_status` |

Use a `.env.example` file with the variable names (no values) and keep any real `.env` out of git.

---

## Instructions for Claude Code

This section is written for Claude Code. Work through the tasks in order. After each task, run its check and fix problems before moving on. Ask before doing anything outside this folder, and never print, commit or log secret values.

### Task 1: Initialise the project

1. If there is no `pyproject.toml`, run `uv init --no-workspace` in this folder, then delete any generated `hello.py` or `main.py` that isn't one of the files listed above.
2. Install dependencies:
   ```bash
   uv add "fastmcp>=4" fastapi uvicorn anthropic
   uv add --dev pytest pytest-asyncio httpx
   ```
3. If this folder isn't inside a git repository, run `git init` and make an initial commit so the git tools have history to read.
4. Create `.gitignore` covering `.venv/`, `__pycache__/`, `.env` and `.pytest_cache/`.
5. Create `.env.example` listing every variable from the configuration table, with empty values.

**Check:** `uv run python -c "import fastmcp, fastapi, anthropic; print(fastmcp.__version__)"` prints a version of 4 or higher.

### Task 2: Add sample data

Create `logs/app.log` with about 30 realistic lines from a small web service: mostly `INFO`, a few `WARN`, and at least two `ERROR` lines, one followed by a short Python stack trace (for example a `KeyError` in an order-handling function). Create a second, quieter file `logs/worker.log` so autocomplete has more than one option.

**Check:** `ls logs` shows both files.

### Task 3: Verify the MCP server

1. Run `uv run python -m py_compile server.py`.
2. Confirm every import in `server.py` resolves against the installed fastmcp. The server targets FastMCP 4 on MCP SDK v2: decorators are used without parentheses (`@mcp.tool`, `@mcp.resource(...)`, `@mcp.prompt`, `@mcp.completion`), and `Completion`, `PromptReference` and `ResourceTemplateReference` come from `mcp.types`. If anything differs in the installed version, check the official docs at gofastmcp.com and make the smallest change that fixes it.
3. Start the inspector with `uv run fastmcp dev server.py` only if the person asks; otherwise rely on the tests in Task 4.

**Check:** `uv run python -c "import server"` exits without errors.

### Task 4: Write smoke tests

Create `tests/test_server.py` using the in-memory client (`fastmcp.Client(server.mcp)`), with no network or subprocess. Set `DEV_REPO_PATH` and `DEV_LOG_DIR` to this folder and its `logs/` folder before importing `server`, so the tests don't depend on where they're run from. Cover:

- `list_tools()` includes `recent_commits`, `search_logs`, `run_tests`, `check_health` and `ci_status`.
- `call_tool("recent_commits", {"limit": 3})` returns text containing an `exit code 0` line.
- `call_tool("search_logs", {"filename": "app.log", "contains": "ERROR"})` returns only lines containing `ERROR`.
- `search_logs` with `filename` set to `"../server.py"` does not return the file's contents (path traversal is blocked).
- `get_prompt("explain_failure", {"log_file": "app.log"})` returns a message mentioning `app.log`.
- Completion for prompt `explain_failure`, argument `log_file`, partial value `"ap"` includes `app.log` and excludes `worker.log`.
- Completion for resource template `logs://{filename}` with an empty value lists both log files.
- Reading resource `config://env-keys` returns names only, never values.

The exact signature of `Client.complete(...)` varies between fastmcp versions. Check the installed version's signature (for example with `inspect.signature`) and use that, then update `app.py`'s `/api/complete` endpoint to match if needed.

**Check:** `uv run pytest -q` passes.

### Task 5: Verify the web app

1. Run `uv run python -m py_compile app.py`.
2. Add `tests/test_app.py` using FastAPI's `TestClient` (as a context manager, so the app's lifespan opens the MCP session):
   - `GET /` returns 200 and HTML containing "Why did this fail?".
   - `GET /api/complete?value=ap` returns JSON whose `values` include `app.log`.
   - `POST /api/run` with an empty `log_file` returns 400.
   - Do not call the real Claude API in tests. If you test `/api/run` beyond validation, mock `app.claude.messages.create`.
3. If `ANTHROPIC_API_KEY` is set in the environment, start the server with `uv run uvicorn app:app --reload` and tell the person to open http://localhost:8000. If it isn't set, tell them how to set it and stop there.

**Check:** `uv run pytest -q` passes for both test files.

### Task 6: Connect the server to Claude Code (only if the person asks)

```bash
claude mcp add dev-companion \
  -e DEV_REPO_PATH="$(pwd)" \
  -e DEV_LOG_DIR="$(pwd)/logs" \
  -- uv run --directory "$(pwd)" server.py
```

Then confirm with `claude mcp list`. In a new Claude Code session, MCP resources can be attached with `@` mentions and the server's prompts appear as slash commands.

### Rules while working

- Keep the security properties already in the code: tools run allowlisted commands only, `search_logs` stays inside the log folder, `check_health` only calls configured URLs, `config://env-keys` returns names only, and `app.py` exposes only the tools in `ALLOWED_TOOLS`.
- Don't add `print()` to `server.py`. Over stdio, stdout carries the protocol, so log to stderr instead.
- Prefer small, targeted fixes over rewrites, and explain any change to `server.py` or `app.py` in one or two sentences when you finish.
- When everything passes, summarise what was set up, what was changed, and the exact command to start the app.

---

## Running it yourself

```bash
uv sync
export ANTHROPIC_API_KEY=your-key          # PowerShell: $env:ANTHROPIC_API_KEY="your-key"
uv run uvicorn app:app --reload            # then open http://localhost:8000
uv run pytest -q                           # run the smoke tests
uv run fastmcp dev server.py               # explore the server in the MCP Inspector
```

## What the server exposes

**Tools:** `recent_commits`, `changed_files`, `run_tests` (pytest, npm or maven only), `search_logs`, `check_health`, `ci_status`.

**Resources:** `project://conventions`, `project://dependencies`, `project://tree`, `api://openapi`, `config://env-keys`.

**Resource templates (with autocomplete):** `logs://{filename}`, `git://commit/{sha}`, `git://diff/{branch}` (branch names containing `/` are URL-encoded).

**Prompts (with autocomplete):** `pre_merge_check(base)`, `explain_failure(log_file)`, `write_tests_for(path)`, `investigate_service(service)`.

## Troubleshooting

- **`AttributeError` or import errors from `mcp`:** an older server built on MCP SDK v1 has met SDK v2. This project uses `fastmcp>=4`; make sure the environment didn't also pin `mcp<2`.
- **Autocomplete shows nothing:** check that `DEV_LOG_DIR` points at a folder with files in it, and that `/api/complete?value=` returns values in the browser.
- **Diagnose fails immediately:** `ANTHROPIC_API_KEY` is missing or invalid, or `ANTHROPIC_MODEL` names a model your key can't use.
- **Git tools return errors:** `DEV_REPO_PATH` isn't a git repository, or it has no commits yet.

## Next steps

- Add a prompt picker to the page that builds its inputs from `list_prompts()`, so one page serves every prompt.
- Add connectors for internal systems, such as Jira tickets, database schemas or Kubernetes pods, each with autocomplete.
- Move to the HTTP transport (`mcp.run(transport="http")`) with authentication so a team can share one hosted server.
