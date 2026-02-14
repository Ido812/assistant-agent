# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```bash
source venv/bin/activate
python main.py
```

Requires a `GEMINI_API_KEY` in `.env`. The schedule agent also requires Google Calendar OAuth files (`credentials.json` for initial auth, `token.json` is auto-generated after first login).

## Dependencies

```bash
pip install -r requirements.txt
```

Key packages: `google-genai`, `python-dotenv`, `yfinance`, `mcp`, `google-api-python-client`, `google-auth-oauthlib`

Python 3.11 via local venv (`venv/bin/python`).

## Architecture

This is a multi-agent routing system powered by Google Gemini (`gemini-2.5-flash`). A user types a message in the CLI, and it gets classified and dispatched to a specialized agent.

**Router ([main.py](main.py))** — Uses Gemini as a classifier with a system prompt that categorizes user input into: `stock`, `work`, `knowledge`, `schedule`, or `unknown`. The `work` category handles all teaching finances (payments, earnings, salary). The `schedule` category handles calendar/time planning only. The classifier returns structured JSON with category, confidence, reason, and a reformulated mission string. The mission is then forwarded to the appropriate agent.

**Knowledge Agent ([agents/knowledge.py](agents/knowledge.py))** — A Gemini chat session for math/CS/physics tutoring. Receives the mission string and returns a step-by-step answer. Maintains conversation history within a session via `genai.Client.chats`.

**Stock Agent ([agents/stock.py](agents/stock.py))** — Connects to the stock MCP server as a subprocess, discovers its tools, converts MCP tool schemas to Gemini function declarations, and runs a tool-calling loop until Gemini produces a final text answer. Manages its own conversation history manually via a `_history` list.

**Stock MCP Server ([mcp_servers/stock_mcp.py](mcp_servers/stock_mcp.py))** — A `FastMCP` server exposing three tools via stdio: `get_stock_price`, `get_stock_history`, `get_company_info`. All use `yfinance` for data.

**Schedule Agent ([agents/schedule.py](agents/schedule.py))** — Handles calendar management and earnings calculations. Connects to the schedule MCP server, converts tools to Gemini function declarations, and runs a tool-calling loop. Manages its own `_history` list. User timezone is `Asia/Jerusalem`. The router sends both scheduling and earnings/salary questions here.

**Schedule MCP Server ([mcp_servers/schedule_mcp.py](mcp_servers/schedule_mcp.py))** — A `FastMCP` server exposing Google Calendar tools via stdio: `list_events`, `create_event`, `delete_event`, `update_event`, `calculate_earnings`. Uses Google OAuth2 for Calendar API access. `calculate_earnings` reads lesson data directly from the calendar and applies pricing rules (Noam=130, Shoham=200, default=150). OAuth files (`credentials.json`, `token.json`) live in the project root.

**Work Agent ([agents/work.py](agents/work.py))** — Handles all teaching finances. Connects to the work MCP server for CSV operations and can call the schedule agent (via a `query_schedule` tool). For payment questions (who paid, who didn't, how much owed): goes directly to the CSV. For earnings questions: queries the schedule agent (which calculates from the calendar), then syncs any missing past lessons to the CSV. All past lessons default to `paid=yes` unless the user explicitly says otherwise.

**Work MCP Server ([mcp_servers/work_mcp.py](mcp_servers/work_mcp.py))** — A `FastMCP` server exposing CSV tools: `read_lessons`, `add_lesson`, `update_payment`, `get_all_lessons`. Manages `data/work_ledger.csv` with columns: student_name, date, price, paid, payment_date.

### Key patterns

- Each agent exposes a `solve(mission: str) -> str` function that `main.py` imports and calls.
- MCP-based agents (stock, schedule, work) bridge sync/async with `asyncio.run()` and share the same structure: subprocess MCP server, schema conversion via `_mcp_tools_to_gemini()`, and a tool-calling loop.
- The work agent is unique: it can call the schedule agent directly for cross-agent data retrieval.
- To add a new agent: create `agents/<name>.py` with a `solve(mission)` function, optionally a `mcp_servers/<name>_mcp.py` server if tools are needed, add the category to the router's system prompt in `main.py`, and add the routing branch in `main()`.
