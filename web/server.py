"""
server.py — Web server for the Assistant Agent.

This is a web entry point for the app:
  - main.py  = CLI (you type in the terminal)
  - server.py = Web server (your phone's browser talks to it)

How to run locally:
  source venv/bin/activate
  pip install fastapi uvicorn[standard]
  uvicorn web.server:app --reload --port 8000

During development, test on your phone via http://<your-mac-ip>:8000
Once deployed to Google Cloud, it works from anywhere via a public URL.
"""

import asyncio
import json
import os
import sys

# Add the project root (one level up from web/) to Python's import path,
# so we can import main.py, agents/, etc. that live in the project root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# FastAPI is a Python web framework — it creates HTTP endpoints
# (URLs your phone app sends requests to and gets responses from).
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────────────────────────────
# Imports from the existing codebase.
#
# When Python imports main.py, it runs the module-level code which
# creates the Gemini client, configs, and loads chat history.
# The main() CLI loop does NOT run (protected by if __name__ == "__main__").
# All objects below are the same live objects from main.py — not copies.
# ──────────────────────────────────────────────────────────────────────
from main import (
    classify,                          # Takes user text → returns {category, confidence, reason, mission}
    _client,                           # Gemini client for fallback answers
    _MODEL,                            # Model name
    _FALLBACK_CONFIG,                  # Config for fallback (unknown) answers
    _last_exchanges,                   # The same list object from main.py — shared reference
)
from agents.memory import save_last_exchanges   # Saves chat history to disk
from agents.knowledge import solve as knowledge_solve
from agents.stock import solve as stock_solve
from agents.schedule import solve as schedule_solve
from agents.work import solve as work_solve

# ──────────────────────────────────────────────────────────────────────
# This lock ensures only one message is processed at a time.
# The agents use internal state (_history lists) that aren't safe for
# concurrent access. Since this is a single-user app, we process one
# message at a time — same as the CLI where you wait for a response.
# ──────────────────────────────────────────────────────────────────────
_chat_lock = asyncio.Lock()

# ──────────────────────────────────────────────────────────────────────
# Create the web application
# ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="Assistant Agent")

# CORS = "Cross-Origin Resource Sharing". During local development,
# the React frontend runs on port 5173 and the backend on port 8000.
# Browsers block requests between different ports by default (security).
# This tells the browser: "it's OK for port 5173 to talk to port 8000".
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Map category names to the matching solve() functions
_SOLVERS = {
    "knowledge": knowledge_solve,
    "stock": stock_solve,
    "schedule": schedule_solve,
    "work": work_solve,
}


def _route_and_solve(user_input: str) -> dict:
    """
    The core routing logic — same flow as main.py's while-loop:
    1. Classify the user's message (with chat history for context)
    2. If unknown, give a general fallback answer
    3. Call the matching agent's solve() function
    4. Save the exchange to chat history

    This runs in a background thread because solve() functions use
    asyncio.run() internally, which would conflict with the web server's
    own async loop.
    """
    result = classify(user_input)
    category = result["category"]

    # Unknown: fallback to general answer
    if category == "unknown":
        fallback = _client.models.generate_content(
            model=_MODEL, contents=user_input, config=_FALLBACK_CONFIG,
        )
        return {
            "answer": fallback.text.strip(),
            "category": "unknown",
            "confidence": 0,
            "reason": "No matching category",
            "mission": "",
        }

    mission = result["mission"]
    solver = _SOLVERS.get(category)
    if not solver:
        return {"error": f"Unknown category: {category}"}

    answer = solver(mission)

    # Save to chat history
    _last_exchanges.append({"role": "user", "text": f"[{category}] {mission}"})
    _last_exchanges.append({"role": "model", "text": answer})
    save_last_exchanges(_last_exchanges)

    return {
        "answer": answer,
        "category": category,
        "confidence": result["confidence"],
        "reason": result["reason"],
        "mission": mission,
    }


# ══════════════════════════════════════════════════════════════════════
# API ENDPOINTS — The URLs your phone app calls
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/health")
async def health():
    """Simple check — is the server running?"""
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(request: Request):
    """
    Main chat endpoint.

    Phone sends:    POST /api/chat  {"message": "what is 2+2?"}
    Server returns: {"answer": "...", "category": "knowledge", "confidence": 0.95, ...}
    """
    body = await request.json()
    user_input = body.get("message", "").strip()
    if not user_input:
        return JSONResponse({"error": "Empty message"}, status_code=400)

    async with _chat_lock:
        loop = asyncio.get_event_loop()
        try:
            # run_in_executor runs the function in a separate thread,
            # needed because solve() internally calls asyncio.run()
            result = await loop.run_in_executor(None, _route_and_solve, user_input)
            if "error" in result and "answer" not in result:
                return JSONResponse(result, status_code=500)
            return JSONResponse(result)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/chat/stream")
async def chat_stream(request: Request):
    """
    Streaming chat endpoint using Server-Sent Events (SSE).

    Instead of waiting for the full response, sends progress updates:
    1. "thinking"   — immediately (phone shows typing animation)
    2. "classified" — once category is known (phone shows "Checking stocks...")
    3. "answer"     — the final response from the agent

    This makes the app feel responsive even when agents take a few seconds.
    """
    body = await request.json()
    user_input = body.get("message", "").strip()
    if not user_input:
        return JSONResponse({"error": "Empty message"}, status_code=400)

    async def event_generator():
        # Step 1: Tell the phone "I'm thinking..."
        yield f"data: {json.dumps({'type': 'thinking'})}\n\n"

        async with _chat_lock:
            loop = asyncio.get_event_loop()
            try:
                # Step 2: Classify the message (with chat history for context)
                result = await loop.run_in_executor(None, classify, user_input)
                category = result["category"]

                # Unknown: fallback to general answer
                if category == "unknown":
                    fallback = await loop.run_in_executor(
                        None,
                        lambda: _client.models.generate_content(
                            model=_MODEL, contents=user_input, config=_FALLBACK_CONFIG,
                        ),
                    )
                    yield f"data: {json.dumps({'type': 'answer', 'answer': fallback.text.strip(), 'category': 'unknown', 'confidence': 0, 'reason': 'No matching category', 'mission': ''})}\n\n"
                    return

                # Step 3: Tell the phone which agent is working
                yield f"data: {json.dumps({'type': 'classified', 'category': category, 'confidence': result['confidence']})}\n\n"

                # Step 4: Run the agent
                mission = result["mission"]
                solver = _SOLVERS.get(category)
                if not solver:
                    yield f"data: {json.dumps({'type': 'error', 'error': f'Unknown category: {category}'})}\n\n"
                    return

                answer = await loop.run_in_executor(None, solver, mission)

                # Save to chat history
                _last_exchanges.append({"role": "user", "text": f"[{category}] {mission}"})
                _last_exchanges.append({"role": "model", "text": answer})
                await loop.run_in_executor(
                    None, save_last_exchanges, _last_exchanges
                )

                # Step 5: Send the final answer
                yield f"data: {json.dumps({'type': 'answer', 'answer': answer, 'category': category, 'confidence': result['confidence'], 'reason': result['reason'], 'mission': mission})}\n\n"

            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ══════════════════════════════════════════════════════════════════════
# STATIC FILE SERVING
#
# In production, after building the React frontend (npm run build),
# the compiled HTML/CSS/JS files end up in frontend/dist/.
# This code tells FastAPI to serve those files, so the same server
# handles both the API (/api/*) and the UI (everything else).
#
# During local development you don't need this — Vite serves the
# frontend directly on port 5173 and proxies API calls to port 8000.
# ══════════════════════════════════════════════════════════════════════

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend", "dist")

if os.path.isdir(_FRONTEND_DIR):
    # Serve JS/CSS/image files from the "assets" folder
    _assets_dir = os.path.join(_FRONTEND_DIR, "assets")
    if os.path.isdir(_assets_dir):
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

    @app.get("/manifest.json")
    async def manifest():
        """PWA manifest — tells the phone how to install the app on home screen."""
        return FileResponse(os.path.join(_FRONTEND_DIR, "manifest.json"))

    @app.get("/sw.js")
    async def service_worker():
        """Service worker — enables PWA features (offline shell, home screen icon)."""
        return FileResponse(
            os.path.join(_FRONTEND_DIR, "sw.js"),
            media_type="application/javascript",
        )

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """
        Catch-all: any URL that isn't /api/* gets the React app's index.html.
        This lets React handle client-side routing.
        """
        file_path = os.path.join(_FRONTEND_DIR, path)
        if path and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(_FRONTEND_DIR, "index.html"))


# This lets you press the Play button in VS Code (or run `python server.py`)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
