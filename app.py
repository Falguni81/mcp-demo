"""
One-page MCP app: "Why did this fail?" built on the dev-companion server.

The page uses three MCP features end to end:
  completion  -> autocompletes the log file name as you type
  prompt      -> loads the explain_failure prompt from the server
  tools       -> Claude calls the server's tools (search_logs, recent_commits, ...)

Setup (in the same folder as server.py and index.html):
    uv add "fastmcp>=4" fastapi uvicorn anthropic
    export ANTHROPIC_API_KEY=...        # PowerShell: $env:ANTHROPIC_API_KEY="..."
    export DEV_REPO_PATH=/path/to/your/repo
    uv run uvicorn app:app --reload
    # open http://localhost:8000
"""

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from anthropic import AsyncAnthropic
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastmcp import Client
from mcp.types import PromptReference
from pydantic import BaseModel

from server import mcp  # the dev-companion server, run in-process (no subprocess)

PROMPT_NAME = "explain_failure"
PROMPT_ARG = "log_file"
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
MAX_TURNS = 8
# Least privilege: this page only diagnoses, so it can't run tests or anything else.
ALLOWED_TOOLS = {"search_logs", "recent_commits", "changed_files", "check_health", "ci_status"}

claude = AsyncAnthropic()  # reads ANTHROPIC_API_KEY
mcp_client = Client(mcp)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with mcp_client:  # one MCP session for the life of the app
        yield


app = FastAPI(lifespan=lifespan)


def _text(blocks) -> str:
    return "\n".join(b.text for b in blocks if getattr(b, "text", None))


@app.get("/")
def index():
    return FileResponse(Path(__file__).with_name("index.html"))


@app.get("/api/complete")
async def complete(value: str = ""):
    """MCP completion: suggestions for the prompt's log_file argument."""
    result = await mcp_client.complete(
        PromptReference(type="ref/prompt", name=PROMPT_NAME),
        {"name": PROMPT_ARG, "value": value},
    )
    return {"values": list(result.values)}


class RunRequest(BaseModel):
    log_file: str


async def run_agent(log_file: str):
    def event(**data) -> str:
        return json.dumps(data, default=str) + "\n"

    try:
        # 1. MCP prompt: the server owns the instructions, the app just fills the argument.
        prompt = await mcp_client.get_prompt(PROMPT_NAME, {PROMPT_ARG: log_file})
        user_text = "\n".join(_text([m.content]) for m in prompt.messages)
        yield event(type="prompt", text=user_text)

        # 2. MCP tools, translated into the Claude API's tool format.
        tools = [
            {
                "name": t.name,
                "description": t.description or "",
                "input_schema": getattr(t, "input_schema", None)
                or getattr(t, "inputSchema", None)
                or {"type": "object"},
            }
            for t in await mcp_client.list_tools()
            if t.name in ALLOWED_TOOLS
        ]

        # 3. Agent loop: Claude asks for tools, we run them through MCP, repeat.
        messages = [{"role": "user", "content": user_text}]
        for _ in range(MAX_TURNS):
            resp = await claude.messages.create(
                model=MODEL, max_tokens=2000, tools=tools, messages=messages
            )
            messages.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason != "tool_use":
                yield event(type="answer", text=_text(resp.content))
                return

            results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                yield event(type="tool_call", name=block.name, input=block.input)
                if block.name not in ALLOWED_TOOLS:
                    out, is_error = f"Tool '{block.name}' is not available here.", True
                else:
                    try:
                        out, is_error = _text((await mcp_client.call_tool(block.name, block.input)).content), False
                    except Exception as e:  # noqa: BLE001 - hand the error back to Claude
                        out, is_error = f"Tool error: {e}", True
                yield event(type="tool_result", name=block.name, preview=out[:1500], error=is_error)
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": out[:8000] or "(empty)", "is_error": is_error})
            messages.append({"role": "user", "content": results})

        yield event(type="error", message=f"Stopped after {MAX_TURNS} rounds without a final answer.")
    except Exception as e:  # noqa: BLE001
        yield event(type="error", message=str(e))


@app.post("/api/run")
async def run(req: RunRequest):
    log_file = req.log_file.strip()
    if not log_file:
        raise HTTPException(400, "Choose a log file first.")
    return StreamingResponse(run_agent(log_file), media_type="application/x-ndjson")
