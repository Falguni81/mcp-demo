"""Smoke tests for the dev-companion MCP server, using the in-memory client.

conftest.py sets DEV_REPO_PATH and DEV_LOG_DIR before `server` is imported.
"""

import pytest
from fastmcp import Client
from mcp.types import PromptReference, ResourceTemplateReference

import server


@pytest.fixture
async def client():
    async with Client(server.mcp) as c:
        yield c


def _text(result) -> str:
    return "\n".join(b.text for b in result.content if getattr(b, "text", None))


async def test_lists_core_tools(client):
    names = {t.name for t in await client.list_tools()}
    assert {"recent_commits", "search_logs", "run_tests", "check_health", "ci_status"} <= names


async def test_recent_commits(client):
    out = _text(await client.call_tool("recent_commits", {"limit": 3}))
    assert "exit code 0" in out.splitlines()


async def test_search_logs_filters(client):
    out = _text(await client.call_tool("search_logs", {"filename": "app.log", "contains": "ERROR"}))
    lines = out.splitlines()
    # Matching is case-insensitive, so "KeyError: ..." counts as a hit too.
    assert lines and all("error" in line.lower() for line in lines)
    assert "INFO" not in out


async def test_search_logs_blocks_path_traversal(client):
    out = _text(await client.call_tool("search_logs", {"filename": "../server.py"}))
    assert out.startswith("Not found")
    assert "FastMCP" not in out


async def test_explain_failure_prompt(client):
    prompt = await client.get_prompt("explain_failure", {"log_file": "app.log"})
    assert any("app.log" in getattr(m.content, "text", "") for m in prompt.messages)


async def test_prompt_completion(client):
    result = await client.complete(
        PromptReference(type="ref/prompt", name="explain_failure"),
        {"name": "log_file", "value": "ap"},
    )
    assert "app.log" in result.values
    assert "worker.log" not in result.values


async def test_resource_template_completion(client):
    result = await client.complete(
        ResourceTemplateReference(type="ref/resource", uri="logs://{filename}"),
        {"name": "filename", "value": ""},
    )
    assert {"app.log", "worker.log"} <= set(result.values)


async def test_env_keys_are_names_only(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-secret-value")
    contents = await client.read_resource("config://env-keys")
    text = "\n".join(getattr(c, "text", "") for c in contents)
    assert "ANTHROPIC_API_KEY" in text
    assert "=" not in text
    assert "sk-test-secret-value" not in text
