import os
import json

_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "memory"
)
MAX_EXCHANGES = 10  # per-agent: 10 exchanges = 20 entries (10 user + 10 model)
MAX_LAST_EXCHANGES = 20  # router chat history: last 20 entries (10 user + 10 model)


def _ensure_dir():
    os.makedirs(_DATA_DIR, exist_ok=True)


def _trim(history: list[dict]) -> list[dict]:
    """Keep only the last MAX_EXCHANGES exchanges (pairs of user+model)."""
    max_entries = MAX_EXCHANGES * 2
    return history[-max_entries:]


def load_history(agent_name: str) -> list[dict]:
    """Load persisted history for an agent, trimmed to last 10 exchanges.
    Returns list of {"role": "user"|"model", "text": str} dicts.
    Returns empty list if file is missing or corrupt."""
    _ensure_dir()
    path = os.path.join(_DATA_DIR, f"{agent_name}.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        for entry in data:
            if not isinstance(entry, dict) or "role" not in entry or "text" not in entry:
                return []
        return _trim(data)
    except (json.JSONDecodeError, OSError):
        return []


def save_history(agent_name: str, history: list[dict]) -> None:
    """Persist history, keeping only the last MAX_EXCHANGES exchanges."""
    _ensure_dir()
    path = os.path.join(_DATA_DIR, f"{agent_name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_trim(history), f, ensure_ascii=False, indent=2)


def append_exchange(agent_name: str, user_text: str, model_text: str) -> None:
    """Load current history, append one exchange, save (trimmed to 10)."""
    history = load_history(agent_name)
    history.append({"role": "user", "text": user_text})
    history.append({"role": "model", "text": model_text})
    save_history(agent_name, history)


def load_last_exchanges() -> list[dict]:
    """Load the router's chat history (last 20 entries) used for classification context.
    Returns list of {"role": "user"|"model", "text": str} dicts."""
    _ensure_dir()
    path = os.path.join(_DATA_DIR, "last_exchange.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return data[-MAX_LAST_EXCHANGES:]
    except (json.JSONDecodeError, OSError):
        return []


def save_last_exchanges(exchanges: list[dict]) -> None:
    """Save the router's chat history, keeping only the last 20 entries."""
    _ensure_dir()
    path = os.path.join(_DATA_DIR, "last_exchange.json")
    trimmed = exchanges[-MAX_LAST_EXCHANGES:]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)
