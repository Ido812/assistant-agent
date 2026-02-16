import os
import json
from dotenv import load_dotenv
from google import genai
from agents.knowledge import solve as knowledge_solve
from agents.stock import solve as stock_solve
from agents.schedule import solve as schedule_solve
from agents.work import solve as work_solve
from agents.memory import load_last_exchanges, save_last_exchanges

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
- The conversation history contains previous exchanges (user messages and agent responses). Use this to resolve ambiguous follow-ups like "and last month?", "tell me more", "what about Microsoft?", "do the same for Noam", etc.
- When the follow-up continues the same topic, route to the SAME category and craft the mission with the full resolved context (e.g., replace "it" or "that" with the actual subject).
- When the follow-up clearly switches to a new topic, ignore the previous context and classify fresh.

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


# Stateless Gemini client — each classification is a fresh call
_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
_MODEL = "gemini-2.5-flash"

_ROUTER_CONFIG = genai.types.GenerateContentConfig(
    system_instruction=SYSTEM_PROMPT,
    temperature=0.0,
)

_FALLBACK_CONFIG = genai.types.GenerateContentConfig(
    system_instruction="Answer the user's question in a single helpful sentence.",
    temperature=0.3,
)

# Chat history for the router — seeded into each classification call
_last_exchanges = load_last_exchanges()

def _build_chat_history() -> list:
    """Build chat history from the last exchanges for the Gemini chat API.
    Returns list of Content objects in chronological order (oldest to newest)."""
    if not _last_exchanges:
        return []
    recent = _last_exchanges[-10:]
    return [
        genai.types.Content(
            role=entry["role"],
            parts=[genai.types.Part(text=entry["text"])],
        )
        for entry in recent
    ]


def _parse_classification(raw: str) -> dict:
    """Extract JSON classification from Gemini's raw response."""
    text = raw[raw.index("{"):raw.rindex("}") + 1]
    return json.loads(text)


def classify(user_input: str) -> dict:
    """Send user input to Gemini with recent history and return the classification."""
    history = _build_chat_history()
    chat = _client.chats.create(
        model=_MODEL, config=_ROUTER_CONFIG, history=history,
    )
    response = chat.send_message(user_input)
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

            # Handle unknown: fallback to general answer
            if category == "unknown":
                fallback = _client.models.generate_content(
                    model=_MODEL, contents=user_input, config=_FALLBACK_CONFIG,
                )
                print(f"\n  {fallback.text.strip()}\n")
                continue

            mission = result["mission"]
            print(f"\n  Category  : {category}")
            print(f"  Confidece: {confidence}")
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
                _last_exchanges.append({"role": "user", "text": f"[{category}] {mission}"})
                _last_exchanges.append({"role": "model", "text": answer})
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
