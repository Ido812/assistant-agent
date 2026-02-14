import os
from dotenv import load_dotenv
from google import genai
from agents.memory import load_history, append_exchange

load_dotenv()

# System prompt for the knowledge agent
SYSTEM_PROMPT = """You are an expert tutor in mathematics, computer science, and physics.
You receive a mission and must solve it clearly and step by step.
Keep your answers accurate, concise, and easy to understand for a student."""


# Load persisted history and seed the chat session
_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
_persisted = load_history("knowledge")
_initial_history = [{"role": h["role"], "parts": [{"text": h["text"]}]} for h in _persisted]

_chat = _client.chats.create(
    model="gemini-2.5-flash",
    config=genai.types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=0.3,
    ),
    history=_initial_history,
)


def solve(mission: str) -> str:
    """Send a mission and return the answer, keeping history for follow-ups."""
    response = _chat.send_message(mission)
    answer = response.text.strip()
    append_exchange("knowledge", mission, answer)
    return answer
