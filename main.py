import os
import json
from dotenv import load_dotenv
from google import genai
from agents.knowledge import solve as knowledge_solve
from agents.stock import solve as stock_solve
from agents.schedule import solve as schedule_solve
from agents.work import solve as work_solve
from agents.memory import load_history, load_last_exchanges, save_last_exchanges

# Load environment variables from .env file
load_dotenv()

# System prompt that tells the model to classify input
SYSTEM_PROMPT = """You are a routing assistant for a user who works as a private teacher (math, CS, physics) and also invests in the stock exchange. Classify each message into exactly one of the categories below and craft an accurate mission for the downstream agent based on its specific capabilities.

## Categories & Agent Capabilities

### 1. "stock" — Stock market analysis
Route here for: stock prices, market data, company info, investing questions, trading, portfolios, financial instruments.
**Agent capabilities:**
- Get current stock price with daily data (price, change, day range, volume) for any ticker
- Get historical price data for periods: 1d, 5d, 1mo, 3mo, 6mo, 1y, 5y
- Get company fundamentals: sector, industry, market cap, P/E ratio, 52-week range, business summary
**Agent limitations:**
- Cannot execute trades or manage a portfolio
- Cannot access news, analyst ratings, or data beyond what yfinance provides
- Data is from yfinance — only publicly traded tickers

### 2. "work" — Teaching business finances & payment tracking
Route here for: who paid, who didn't pay, how much money is owed, mark payments, earnings/salary/income from lessons, syncing lesson records.
**Agent capabilities:**
- Read lesson records from CSV by month (student name, date, time, price, paid status)
- Add lesson records to CSV
- Update payment status for specific lessons (mark paid/unpaid)
- Get all recorded lessons
- Query the schedule agent internally to calculate earnings from the calendar
- Sync past lessons from calendar to CSV automatically
**Agent limitations:**
- Only tracks PAST lessons (never future ones)
- For earnings calculations, it internally calls the schedule agent — the mission should clearly state the date range
- Cannot create, modify, or delete calendar events — only reads calendar data via the schedule agent
- Pricing is fixed: Noam=130 NIS, Shoham=200 NIS, all others=150 NIS

### 3. "knowledge" — Math, CS, and physics tutoring
Route here for: solving math/CS/physics problems, explaining concepts, proofs, algorithms, preparing lesson content, homework help.
**Agent capabilities:**
- Answer questions and solve problems step by step in math, computer science, and physics
- Explain concepts clearly for students
- Maintains conversation history within the session for follow-up questions
**Agent limitations:**
- Pure conversational — no access to external tools, files, internet, or any data sources
- Cannot access the calendar, stock data, or lesson records
- Cannot perform calculations that require real-world data

### 4. "schedule" — Calendar management & time planning
Route here for: viewing schedule, scheduling/rescheduling lessons, creating/deleting/updating calendar events, personal trainings, meetups, trips, appointments, time/date planning. NOT for earnings or payment questions.
**Agent capabilities:**
- List calendar events in any date range
- Identify the kind of the event by its color - lessons are lavender or flamingo
- Create events with title, start/end time, description, color, and recurrence (RRULE)
- Delete events by ID (will list events first to find the right one)
- Update event fields (title, time, description, color)
- Calculate earnings from calendar lessons (total, per-day, per-student) — but this is only used internally by the work agent
**Agent limitations:**
- Only accesses the primary Google Calendar
- Can identify an event only with date and time
- Cannot manage payments or the CSV ledger
- Cannot send reminders or notifications
- Timezone is fixed to Asia/Jerusalem
- Event colors: Lavender=private lessons, Flamingo=Hihg school lessons, Grape=trainings, Sage=fun/social

### 5. "unknown" — If the message does not clearly fit any category.

## Follow-up & Context Resolution
- The user's message may include a "[Previous context]" block with info about the last exchange (which agent handled it, what the mission was, and a preview of the agent's response).
- Use this context to resolve ambiguous follow-ups like "and last month?", "tell me more", "what about Microsoft?", "do the same for Noam", etc.
- When the follow-up continues the same topic, route to the SAME category and craft the mission with the full resolved context (e.g., replace "it" or "that" with the actual subject).
- When the follow-up clearly switches to a new topic, ignore the previous context and classify fresh.
- If an "[Agent memory]" block is provided, it shows each agent's recent missions. Use this to match the user's message to the correct agent when the topic seems ambiguous. For example, if the stock agent recently discussed "Apple stock" and the user says "what about Google?", route to stock.

## Mission Crafting Guidelines
- The mission should be a clear, actionable task description tailored to what the target agent can actually do.
- Include specific details from the user's message (dates, names, tickers, etc.).
- For follow-ups, ALWAYS resolve references and include the full context in the mission — the downstream agent may not have the same conversation history.
- For "work" earnings questions, always include the date range so the agent can query the schedule agent properly.
- For "schedule" questions, specify whether it's a view, create, update, or delete operation when clear from context.
- For "stock" questions, include the ticker symbol if mentioned.

Respond with ONLY a JSON object in this exact format:
{"category": "<stock or work or knowledge or schedule or unknown>", "confidence": <0.0 to 1.0>, "reason": "<brief explanation>", "mission": "<a clear, actionable task description for the downstream agent that will handle this request>"}

Do not include any other text outside the JSON.
"""


# Chat session — in-session memory only (no persistence for the router itself)
_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
_chat = _client.chats.create(
    model="gemini-2.5-flash",
    config=genai.types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=0.0,
    ),
)

# Last 20 routing results — used as fallback context when the router returns "unknown"
_last_exchanges = load_last_exchanges()

_AGENT_NAMES = ["stock", "knowledge", "schedule", "work"]


def _build_last_exchanges_context() -> str:
    """Build context from the last exchanges log for fallback classification."""
    if not _last_exchanges:
        return ""
    # Show last 5 exchanges as context (enough to disambiguate without flooding)
    recent = _last_exchanges[-5:]
    lines = []
    for ex in recent:
        preview = ex.get("answer", "")[:100]
        lines.append(f"- [{ex['category']}] mission: {ex['mission']} → {preview}")
    return "[Recent exchanges:\n" + "\n".join(lines) + "]"


def _build_agent_memory_summary() -> str:
    """Build a brief summary of each agent's recent missions from their persisted history."""
    lines = []
    for agent in _AGENT_NAMES:
        history = load_history(agent)
        recent_missions = [h["text"] for h in history if h["role"] == "user"][-3:]
        if recent_missions:
            missions_str = "; ".join(f'"{m}"' for m in recent_missions)
            lines.append(f"- {agent}: {missions_str}")
    if not lines:
        return ""
    return "[Agent memory — recent missions per agent:\n" + "\n".join(lines) + "]"


def _parse_classification(raw: str) -> dict:
    """Extract JSON classification from Gemini's raw response."""
    text = raw[raw.index("{"):raw.rindex("}") + 1]
    return json.loads(text)


def classify(user_input: str) -> dict:
    """Send raw user input to Gemini and return the classification."""
    response = _chat.send_message(user_input)
    return _parse_classification(response.text)


def classify_with_last_exchanges(user_input: str) -> dict:
    """Retry classification with recent exchanges context."""
    context = _build_last_exchanges_context()
    if not context:
        return None

    message = (
        f"{context}\n\n"
        f"The previous classification returned 'unknown'. "
        f"Re-examine the user's message using the recent exchanges above to find a matching category.\n\n"
        f"{user_input}"
    )
    response = _chat.send_message(message)
    return _parse_classification(response.text)


def classify_with_agent_memory(user_input: str) -> dict:
    """Retry classification with agent memory context."""
    agent_memory = _build_agent_memory_summary()
    if not agent_memory:
        return None

    message = (
        f"{agent_memory}\n\n"
        f"The previous classification returned 'unknown'. "
        f"Re-examine the user's message using the agent memory above to find a matching category.\n\n"
        f"{user_input}"
    )
    response = _chat.send_message(message)
    return _parse_classification(response.text)


def main():
    # Interactive loop: classify user messages until 'quit'
    print("=== Task Router ===")
    print("Type your message and I'll classify it as 'stock', 'work', 'knowledge', or 'schedule'.")
    print("Type 'quit' to exit.\n")

    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue
        if user_input.lower() == "quit":
            break

        try:
            result = classify(user_input)
            category = result["category"]
            confidence = result["confidence"]
            reason = result["reason"]

            # Handle unknown: fallback 1 → last exchanges, fallback 2 → agent memory
            if category == "unknown":
                retry = classify_with_last_exchanges(user_input)
                if retry and retry.get("category") != "unknown":
                    result = retry
                    category = result["category"]
                    confidence = result["confidence"]
                    reason = result["reason"]
                else:
                    retry = classify_with_agent_memory(user_input)
                    if retry and retry.get("category") != "unknown":
                        result = retry
                        category = result["category"]
                        confidence = result["confidence"]
                        reason = result["reason"]
                    else:
                        print(f"\n  I don't know this subject well. ({reason})")
                        print("  Please try again with a message about stocks or teaching.\n")
                        continue

            mission = result["mission"]
            print(f"\n  Category  : {category}")
            print(f"  Confidence: {confidence}")
            print(f"  Reason    : {reason}")
            print(f"  Mission   : {mission}\n")

            # Route to the relevant agent
            answer = None
            if category == "knowledge":
                print("  --- Knowledge Agent ---")
                answer = knowledge_solve(mission)
                print(f"  {answer}\n")
            elif category == "stock":
                print("  --- Stock Agent ---")
                answer = stock_solve(mission)
                print(f"  {answer}\n")
            elif category == "schedule":
                print("  --- Schedule Agent ---")
                answer = schedule_solve(mission)
                print(f"  {answer}\n")
            elif category == "work":
                print("  --- Work Agent ---")
                answer = work_solve(mission)
                print(f"  {answer}\n")

            # Append to exchange log (in memory + disk)
            if answer:
                _last_exchanges.append({
                    "category": category,
                    "mission": mission,
                    "answer": answer,
                })
                save_last_exchanges(_last_exchanges)
        except BaseException as e:
            import traceback
            traceback.print_exc()
            # Unwrap TaskGroup / ExceptionGroup sub-exceptions
            if hasattr(e, 'exceptions'):
                for i, sub in enumerate(e.exceptions):
                    print(f"\n  --- Sub-exception {i} ---")
                    traceback.print_exception(type(sub), sub, sub.__traceback__)


if __name__ == "__main__":
    main()
