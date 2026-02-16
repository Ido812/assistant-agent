# Assistant Agent

Multi-agent CLI assistant powered by Google Gemini (`gemini-2.5-flash`).

## Setup

```bash
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

Requires `GEMINI_API_KEY` in `.env` and Google Calendar OAuth files (`credentials.json`, `token.json`) for the schedule agent.

## Architecture

Router (`main.py`) classifies user input via Gemini into: `stock`, `work`, `knowledge`, `schedule`, or `unknown`, then dispatches to the matching agent.

**Agents** — each exposes `solve(mission: str) -> str`:
- `knowledge` — Gemini chat for math/CS/physics tutoring
- `stock` — stock data via MCP server + yfinance
- `schedule` — Google Calendar management + earnings calculation
- `work` — teaching finances (CSV payments + schedule agent for earnings)

**MCP Servers** (`mcp_servers/`):
- `stock_mcp.py` — `get_stock_price`, `get_stock_history`, `get_company_info`
- `schedule_mcp.py` — `list_events`, `create_event`, `delete_event`, `update_event`, `calculate_earnings`
- `work_mcp.py` — `read_lessons`, `add_lesson`, `update_payment`, `get_all_lessons`

## Adding a New Agent

1. Create `agents/<name>.py` with a `solve(mission)` function
2. Optionally add `mcp_servers/<name>_mcp.py` if tools are needed
3. Add the category to the router's system prompt in `main.py`
4. Add the routing branch in `main()`

## Web & Deployment

The `web/` folder contains the web version of the app (FastAPI backend + React frontend). Deployed to Google Cloud via Cloudflare tunnel.

- `web/server.py` — FastAPI server wrapping the same routing logic as `main.py`
- `web/frontend/` — React PWA (dark theme, mobile-optimized)
- `web/deploy.sh` — one-command deploy to Google Cloud VM
- Live at: `https://handmade-tax-lincoln-present.trycloudflare.com`
