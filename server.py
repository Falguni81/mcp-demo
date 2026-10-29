"""
dev-companion v2: MCP server POC for everyday engineering work, now with
context resources, resource templates and argument autocompletion.

Setup:
    uv init dev-companion && cd dev-companion
    uv add "fastmcp>=4"
    # copy this file in as server.py
    uv run fastmcp dev server.py      # or: uv run server.py

Environment variables (all optional):
    DEV_REPO_PATH    path to the git repo to work on        (default: cwd)
    DEV_LOG_DIR      folder with application logs            (default: <repo>/logs)
    DEV_SERVICES     JSON map of service name -> health URL
    GITHUB_REPO      "owner/repo" for CI status
    GITHUB_TOKEN     token with read access to Actions

Stdio servers must never print() to stdout; it corrupts the protocol.
"""

import json
import os
import subprocess
import urllib.request
from pathlib import Path
from urllib.parse import quote, unquote

from fastmcp import FastMCP
from mcp.types import Completion, PromptReference, ResourceTemplateReference

REPO = Path(os.environ.get("DEV_REPO_PATH", ".")).resolve()
LOG_DIR = Path(os.environ.get("DEV_LOG_DIR", REPO / "logs")).resolve()
SERVICES: dict[str, str] = json.loads(os.environ.get("DEV_SERVICES", "{}"))
MAX_OUTPUT = 8000
SOURCE_EXT = {".py", ".ts", ".tsx", ".js", ".java", ".go", ".kt", ".cs", ".rb"}

TEST_RUNNERS = {
    "pytest": ["pytest", "-q", "--maxfail=5"],
    "npm": ["npm", "test", "--silent"],
    "maven": ["mvn", "-q", "test"],
}

mcp = FastMCP("dev-companion")


# ================================================================== helpers
def _run(cmd: list[str], timeout: int = 120) -> str:
    try:
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s: {' '.join(cmd)}"
    out = (r.stdout + r.stderr).strip() or "(no output)"
    return f"exit code {r.returncode}\n{out[-MAX_OUTPUT:]}"


def _git_lines(args: list[str]) -> list[str]:
    try:
        r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    return [l.strip() for l in r.stdout.splitlines() if l.strip()] if r.returncode == 0 else []


def _read_first(names: list[str]) -> str | None:
    """Concatenate whichever of these repo files exist (truncated)."""
    parts = [f"## {n}\n{(REPO / n).read_text(errors='replace')[:MAX_OUTPUT]}"
             for n in names if (REPO / n).is_file()]
    return "\n\n".join(parts) if parts else None


# Candidate suppliers: these feed autocomplete.
def branches() -> list[str]:
    return _git_lines(["for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes"])


def recent_shas() -> list[str]:
    return _git_lines(["log", "-50", "--pretty=format:%h"])


def source_files() -> list[str]:
    return [f for f in _git_lines(["ls-files"]) if Path(f).suffix in SOURCE_EXT]


def log_files() -> list[str]:
    return sorted(p.name for p in LOG_DIR.glob("*") if p.is_file()) if LOG_DIR.is_dir() else []


def services() -> list[str]:
    return list(SERVICES)


# ======================================================= tools (actions)
@mcp.tool
def recent_commits(limit: int = 10) -> str:
    """List recent git commits (hash | author | date | subject)."""
    return _run(["git", "log", f"-{max(1, min(limit, 50))}",
                 "--pretty=format:%h | %an | %ad | %s", "--date=short"])


@mcp.tool
def changed_files(base: str = "main") -> str:
    """Show files changed on the current branch compared with a base branch."""
    return _run(["git", "diff", "--stat", f"{base}...HEAD"])


@mcp.tool
def run_tests(runner: str = "pytest") -> str:
    """Run the project's test suite. runner is one of: pytest, npm, maven."""
    if runner not in TEST_RUNNERS:
        return f"Unsupported runner '{runner}'. Choose from {list(TEST_RUNNERS)}."
    return _run(TEST_RUNNERS[runner], timeout=600)


@mcp.tool
def search_logs(filename: str, contains: str = "", lines: int = 100) -> str:
    """Last N lines of a log file, optionally only lines containing some text."""
    path = (LOG_DIR / filename).resolve()
    if LOG_DIR not in path.parents or not path.is_file():
        return f"Not found. Available logs: {log_files()}"
    rows = path.read_text(errors="replace").splitlines()
    if contains:
        rows = [r for r in rows if contains.lower() in r.lower()]
    return "\n".join(rows[-max(1, min(lines, 500)):]) or "(no matching lines)"


@mcp.tool
def check_health(service: str) -> str:
    """Call a configured service's health endpoint. Use 'all' to check every one."""
    targets = SERVICES if service == "all" else {service: SERVICES.get(service)}
    results = []
    for name, url in targets.items():
        if not url:
            results.append(f"{name}: unknown service. Configured: {services()}")
            continue
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                results.append(f"{name}: HTTP {resp.status} {resp.read(300).decode(errors='replace')}")
        except Exception as e:  # noqa: BLE001
            results.append(f"{name}: DOWN ({e})")
    return "\n".join(results)


@mcp.tool
def ci_status(limit: int = 5) -> str:
    """Show the latest GitHub Actions workflow runs for the configured repo."""
    repo, token = os.environ.get("GITHUB_REPO"), os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        return "Set GITHUB_REPO and GITHUB_TOKEN to enable CI status."
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/actions/runs?per_page={min(limit, 20)}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        runs = json.load(resp).get("workflow_runs", [])
    return "\n".join(f"{r['name']} | {r['head_branch']} | {r['status']}/{r['conclusion']} | "
                     f"{r['html_url']}" for r in runs) or "No runs found."


# ============================== static resources (context that shapes code)
@mcp.resource("project://conventions")
def conventions() -> str:
    """Team coding conventions, lint and formatting rules. Attach this so
    generated code matches house style."""
    return _read_first(["CLAUDE.md", "CONTRIBUTING.md", "docs/CONVENTIONS.md", ".editorconfig",
                        "ruff.toml", ".eslintrc.json", ".prettierrc", "checkstyle.xml"]) \
        or "No convention files found."


@mcp.resource("project://dependencies")
def dependencies() -> str:
    """Declared dependencies and versions, so suggestions use libraries
    (and APIs of those versions) the project actually has."""
    return _read_first(["pyproject.toml", "requirements.txt", "package.json", "pom.xml",
                        "build.gradle", "build.gradle.kts", "go.mod"]) or "No manifest found."


@mcp.resource("project://tree")
def project_tree() -> str:
    """Tracked files in the repo, so the model knows where things live."""
    files = _git_lines(["ls-files"])
    return f"{len(files)} tracked files\n" + "\n".join(files[:400])


@mcp.resource("api://openapi")
def openapi_spec() -> str:
    """The service's OpenAPI spec: real endpoints, payloads and field names."""
    return _read_first(["openapi.yaml", "openapi.json", "docs/openapi.yaml", "swagger.json"]) \
        or "No OpenAPI spec found."


@mcp.resource("config://env-keys")
def env_keys() -> str:
    """Names of configuration variables from .env.example (names only, never values)."""
    path = REPO / ".env.example"
    if not path.is_file():
        return "No .env.example found."
    keys = [l.split("=", 1)[0].strip() for l in path.read_text().splitlines()
            if "=" in l and not l.lstrip().startswith("#")]
    return "\n".join(keys)


# =========================== resource templates (parameterised, completable)
@mcp.resource("logs://{filename}")
def log_resource(filename: str) -> str:
    """The tail of one log file."""
    return search_logs(unquote(filename), lines=300)


@mcp.resource("git://commit/{sha}")
def commit_resource(sha: str) -> str:
    """One commit: message, author and changed files."""
    if not sha.isalnum():
        return "Invalid commit hash."
    return _run(["git", "show", "--stat", "--format=%H%n%an <%ae>%n%ad%n%n%B", sha])


@mcp.resource("git://diff/{branch}")
def diff_resource(branch: str) -> str:
    """Full diff of a branch against main. Branch names with '/' are URL-encoded."""
    return _run(["git", "diff", f"main...{unquote(branch)}"])


# ====================================== prompts (slash-command workflows)
@mcp.prompt
def pre_merge_check(base: str = "main") -> str:
    """Review the current branch before raising a PR."""
    return (f"Use changed_files with base '{base}' and recent_commits to summarise this branch. "
            "Then run_tests and report failures with likely causes. Check the changes against "
            "the project://conventions resource. Finish with a PR description and risk checklist.")


@mcp.prompt
def explain_failure(log_file: str) -> str:
    """Diagnose errors in a log file."""
    return (f"Use search_logs on '{log_file}' with contains='ERROR', then 'Exception'. "
            "Group the errors, find the earliest root cause, link it to recent_commits if "
            "plausible, and suggest a fix.")


@mcp.prompt
def write_tests_for(path: str) -> str:
    """Write unit tests for one source file in the team's style."""
    return (f"Write unit tests for {path}. Read project://conventions and "
            "project://dependencies first, use only the test framework already in use, "
            "cover edge cases and error paths, then run_tests to confirm they pass.")


@mcp.prompt
def investigate_service(service: str) -> str:
    """Check whether a service is healthy and why not."""
    return (f"Run check_health for '{service}'. If it is down or slow, check ci_status for a "
            "recent failed deploy and search_logs for related errors, then summarise.")


# ======================================================== autocompletion
# (reference name or URI template, argument name) -> candidate supplier
PROMPT_COMPLETIONS = {
    ("pre_merge_check", "base"): branches,
    ("explain_failure", "log_file"): log_files,
    ("write_tests_for", "path"): source_files,
    ("investigate_service", "service"): services,
}
TEMPLATE_COMPLETIONS = {
    ("logs://{filename}", "filename"): log_files,
    ("git://commit/{sha}", "sha"): recent_shas,
    ("git://diff/{branch}", "branch"): lambda: [quote(b, safe="") for b in branches()],
}


def _rank(candidates: list[str], typed: str, limit: int = 100) -> Completion:
    """Prefix matches first, then substring matches, capped at the protocol's 100."""
    t = typed.lower()
    prefix = [c for c in candidates if c.lower().startswith(t)]
    seen = set(prefix)
    hits = prefix + [c for c in candidates if t in c.lower() and c not in seen]
    return Completion(values=hits[:limit], total=len(hits), has_more=len(hits) > limit)


@mcp.completion
def complete(ref, argument, context):
    if isinstance(ref, PromptReference):
        supplier = PROMPT_COMPLETIONS.get((ref.name, argument.name))
    elif isinstance(ref, ResourceTemplateReference):
        supplier = TEMPLATE_COMPLETIONS.get((ref.uri, argument.name))
    else:
        supplier = None
    return _rank(supplier(), argument.value or "") if supplier else None


if __name__ == "__main__":
    mcp.run()
