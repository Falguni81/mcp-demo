# Demo script: "Why did this fail?"

About 5 minutes. **Bold lines** are what you say; *italic notes* are what you do. See [architecture.md](architecture.md) for the diagrams to show in part 1.

## Before you start

- Start the app:
  ```bash
  cd /Users/falguni.sinha/Documents/projects/ai_coe_team/poc_ideas/mcp_idea_files
  uv run --env-file .env uvicorn app:app --reload --port 8765
  ```
- Open http://localhost:8765 and do one full practice run, so you know the key works and roughly how long Claude takes.
- Reload the page so it's clean. Keep `architecture.md` open in a second tab (VS Code preview or GitHub).
- Optional: open `logs/app.log` in an editor so you can show the raw log.
- The repo has only one commit, so `recent_commits` won't link the failure to a code change. That's fine; just don't promise it will.

---

## 1. The problem (30 seconds)

**When something breaks, the first twenty minutes usually go the same way: open the logs, grep for errors, scroll through a stack trace, check what changed recently, and only then start thinking.**

**We wanted to see how much of that an AI assistant could do for us, safely, using our own tools rather than copy and paste.**

## 2. The idea: MCP (1 minute)

*Show the components diagram in architecture.md.*

**This is built on MCP, the Model Context Protocol. It's an open standard for giving AI assistants access to tools and data.**

**On the right is our MCP server, dev-companion. It wraps everyday engineering work: git history, logs, test runs, service health and CI status. It's one Python file.**

**On the left is a small web app. It doesn't know how to read logs or query git. It asks the MCP server, and Claude decides which tools to use.**

**Because it's a standard, the same server also plugs into Claude Code or Claude Desktop with no changes.**

## 3. Live demo (2–3 minutes)

### Completion

*Click into the Log file box and type `ap`.*

**First, notice the autocomplete. These suggestions don't come from the web page. They come from the MCP server, which looks at the actual log folder. Any MCP client gets the same suggestions, and the server does the same thing for git branches, commits and service names.**

*Pick `app.log`.*

### Prompt

*Click **Diagnose**. The first step, "Loaded the explain_failure prompt", appears. Expand **Show prompt**.*

**The instructions Claude follows aren't hard-coded in this page. They're a prompt stored on the server. If the team finds a better way to investigate failures, we update it once on the server and every client picks it up.**

### Tools

*Steps appear as Claude works: "Called search_logs", then more calls. Expand one **Show result**.*

**Now Claude is driving. It asked for `search_logs` with ERROR, and you can see exactly what the tool returned. Then it searched for exceptions, and it checked recent commits.**

**Each of these is a real call to our server, shown live. Nothing is hidden: you can open every result and check what Claude saw.**

### The answer

*The Diagnosis appears and the status shows how many tool calls Claude made.*

**And here's the diagnosis. It found the KeyError on 'promotions' in build_summary when creating order 58115, explained the likely cause, and suggested a fix. It also picked up the separate webhook signature failure.**

*If you have the raw log open, show it.*

**This is what it worked from: about thirty lines of log. On a real service it would be thousands, and the tools still return only the lines that matter.**

## 4. Is it safe? (1 minute)

*Show the security diagram in architecture.md.*

**The obvious question is what we're letting an AI do. A few guardrails are built in:**

- **This page can only diagnose. The server can run tests, but the web app doesn't give Claude that tool.**
- **Tools run fixed commands only: specific git commands and an allowlist of test runners. There's no shell.**
- **Log search can't escape the log folder. We test that: asking for `../server.py` returns "Not found".**
- **Health checks only call URLs we configured, and the config resource returns variable names, never values.**
- **The API key stays in a local file that git ignores.**

## 5. What's next (30 seconds)

**This is a proof of concept. The next steps we see are:**

- **Host one shared server for the team, over HTTP with authentication.**
- **Add connectors for the systems we use, such as Jira, database schemas or Kubernetes, each with the same autocomplete.**
- **Turn the page into a picker for every prompt on the server, not just this one.**

**Questions?**

---

## Likely questions

**Does our data go to Anthropic?**
The tool results Claude needs to answer, such as matching log lines, are sent to the Claude API. Tool output is capped at 8,000 characters per call. Point it at logs you're allowed to share with the API under your organisation's policy.

**Why not paste the log into a chat?**
Pasting works for one file. Here Claude chooses what to fetch, can combine logs with git history, service health and CI status, and every step is visible and repeatable.

**Can it change code or deploy?**
Not in this demo. The server has no write or deploy tools, and the web app doesn't expose `run_tests`.

**How hard is it to add a tool?**
A Python function with the `@mcp.tool` decorator and a docstring. The docstring becomes the description Claude reads.

**Does it work in Claude Code?**
Yes. Register it with `claude mcp add` (see Task 6 in the README). The prompts then appear as slash commands and the resources can be attached with `@`.

## If something goes wrong

| Symptom | Fix |
|---|---|
| Page won't load | The app isn't running, or another process has the port. Start it on another one with `--port`. |
| Diagnose fails straight away | Check `ANTHROPIC_API_KEY` in `.env`, and that your key can use `ANTHROPIC_MODEL`. |
| No autocomplete suggestions | `DEV_LOG_DIR` is wrong or the `logs/` folder is empty. |
| Claude takes a long time | Keep talking through the steps already on screen. Fall back to screenshots from your practice run. |
