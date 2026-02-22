import asyncio
import logging
import os
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from mcp.server.fastmcp import FastMCP

# Suppress verbose MCP request logs
logging.getLogger("mcp").setLevel(logging.WARNING)

mcp = FastMCP("schedule-tools")

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TIMEZONE = "Asia/Jerusalem"

# OAuth files live in the project root (one level up from mcp_servers/)
_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CREDENTIALS_FILE = os.path.join(_DIR, "credentials.json")
_TOKEN_FILE = os.path.join(_DIR, "token.json")

# Cached credentials and service (service is NOT thread-safe, use _build_calendar_service() for threads)
_creds_cache = None
_service_cache = None

# Human-friendly names for Google Calendar event color IDs
COLOR_NAMES = {
    "1": "Lavender",
    "2": "Sage",
    "3": "Grape",
    "4": "Flamingo",
    "5": "Banana",
    "6": "Tangerine",
    "7": "Peacock",
    "8": "Graphite",
    "9": "Blueberry",
    "10": "Basil",
    "11": "Tomato",
}


def _get_credentials():
    """Authenticate and return cached Google OAuth credentials."""
    global _creds_cache
    if _creds_cache is not None and _creds_cache.valid:
        return _creds_cache

    creds = None
    if os.path.exists(_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(_TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(_CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    _creds_cache = creds
    return _creds_cache


def _get_calendar_service():
    """Return a cached Calendar API service for single-threaded use."""
    global _service_cache
    if _service_cache is not None:
        return _service_cache
    _service_cache = build("calendar", "v3", credentials=_get_credentials(), cache_discovery=False)
    return _service_cache


def _build_calendar_service():
    """Build a fresh Calendar API service — safe to call from any thread."""
    return build("calendar", "v3", credentials=_get_credentials(), cache_discovery=False)


def _to_rfc3339(dt_str: str) -> str:
    """Convert 'YYYY-MM-DD HH:MM' to RFC3339 format."""
    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
    return dt.isoformat()


@mcp.tool()
def list_events(start_date: str, end_date: str) -> str:
    """List Google Calendar events in a date range.
    start_date and end_date should be in YYYY-MM-DD format."""
    service = _get_calendar_service()
    time_min = start_date + "T00:00:00Z"
    time_max = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d") + "T00:00:00Z"

    result = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        timeZone=TIMEZONE,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = result.get("items", [])
    if not events:
        return f"No events found between {start_date} and {end_date}."

    lines = []
    for event in events:
        start = event["start"].get("dateTime", event["start"].get("date"))
        end = event["end"].get("dateTime", event["end"].get("date"))
        color_id = event.get("colorId", "")
        color_name = COLOR_NAMES.get(color_id, "Default") if color_id else "Default"
        lines.append(
            f"ID: {event['id']}\n"
            f"  Title: {event.get('summary', '(No title)')}\n"
            f"  Start: {start}\n"
            f"  End:   {end}\n"
            f"  Color: {color_name}"
        )
    return "\n\n".join(lines)


@mcp.tool()
def create_event(
    summary: str,
    start_time: str,
    end_time: str,
    description: str = "",
    color_id: str = "",
    recurrence: str = "",
) -> str:
    """Create a Google Calendar event.
    start_time and end_time in 'YYYY-MM-DD HH:MM' format.
    color_id is a Google Calendar color ID (1-11).
    recurrence is an RRULE string like 'RRULE:FREQ=WEEKLY;COUNT=10' for recurring events."""
    service = _get_calendar_service()

    event_body = {
        "summary": summary,
        "start": {"dateTime": _to_rfc3339(start_time), "timeZone": TIMEZONE},
        "end": {"dateTime": _to_rfc3339(end_time), "timeZone": TIMEZONE},
    }
    if description:
        event_body["description"] = description
    if color_id:
        event_body["colorId"] = color_id
    if recurrence:
        event_body["recurrence"] = [recurrence]

    event = service.events().insert(calendarId="primary", body=event_body).execute()
    return f"Event created: {event.get('summary')} (ID: {event['id']})\nLink: {event.get('htmlLink')}"


@mcp.tool()
async def delete_event(event_ids: list[str]) -> str:
    """Delete one or more Google Calendar events by their event IDs.
    All deletions run in parallel."""
    def _delete(event_id: str) -> str:
        service = _build_calendar_service()
        try:
            service.events().delete(calendarId="primary", eventId=event_id).execute()
            return f"Event {event_id} deleted successfully."
        except Exception as e:
            return f"❌ ERROR: Failed to delete {event_id}: {e}"

    results = await asyncio.gather(
        *(asyncio.to_thread(_delete, eid.strip()) for eid in event_ids)
    )
    return "\n".join(results)


@mcp.tool()
def update_event(
    event_id: str,
    summary: str = "",
    start_time: str = "",
    end_time: str = "",
    description: str = "",
    color_id: str = "",
) -> str:
    """Update a Google Calendar event. Only non-empty fields are updated.
    start_time and end_time in 'YYYY-MM-DD HH:MM' format.
    color_id is a Google Calendar color ID (1-11)."""
    service = _get_calendar_service()
    try:
        event = service.events().get(calendarId="primary", eventId=event_id).execute()
    except Exception as e:
        return f"Failed to get event {event_id}: {e}"

    if summary:
        event["summary"] = summary
    if start_time:
        event["start"] = {"dateTime": _to_rfc3339(start_time), "timeZone": TIMEZONE}
    if end_time:
        event["end"] = {"dateTime": _to_rfc3339(end_time), "timeZone": TIMEZONE}
    if description:
        event["description"] = description
    if color_id:
        event["colorId"] = color_id

    updated = service.events().update(
        calendarId="primary", eventId=event_id, body=event
    ).execute()
    return f"Event updated: {updated.get('summary')} (ID: {updated['id']})"


# Lesson colors: Default (no colorId) and Lavender (1) = private, Flamingo (4) = Shoham
_LESSON_COLORS = {"", "1", "4"}
# Colors that are never lessons
_NON_LESSON_COLORS = {"2", "3", "5", "6", "7", "8", "9", "10", "11"}

# Pricing rules
_PRICING = {
    "default": 150,
    "noam": 130,
    "נועם": 130,
    "shoham": 200,
    "שוהם": 200,
}


def _get_lesson_price(student_name: str, color_id: str) -> int:
    """Determine lesson price based on student name and event color."""
    name_lower = student_name.lower().strip()
    for key, price in _PRICING.items():
        if key in name_lower:
            return price
    if color_id == "4":  # Flamingo = Shoham
        return 200
    return 150


@mcp.tool()
def calculate_earnings(start_date: str, end_date: str) -> str:
    """Calculate total and per-day earnings for a date range.
    start_date and end_date should be in YYYY-MM-DD format.
    Reads lesson data directly from Google Calendar, applies pricing rules,
    and returns total earnings, per-day breakdown, and per-student summary."""
    service = _get_calendar_service()

    time_min = start_date + "T00:00:00Z"
    time_max = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d") + "T00:00:00Z"

    result = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        timeZone=TIMEZONE,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = result.get("items", [])
    if not events:
        return f"No events found between {start_date} and {end_date}."

    total = 0
    by_day = {}
    by_student = {}
    lesson_count = 0

    for event in events:
        color_id = event.get("colorId", "")
        # Skip non-lesson events
        if color_id in _NON_LESSON_COLORS:
            continue

        student_name = event.get("summary", "(No title)")
        price = _get_lesson_price(student_name, color_id)
        start = event["start"].get("dateTime", event["start"].get("date", ""))
        day = start[:10]  # YYYY-MM-DD

        total += price
        lesson_count += 1
        by_day[day] = by_day.get(day, 0) + price
        by_student[student_name] = by_student.get(student_name, 0) + price

    if lesson_count == 0:
        return f"No lessons found between {start_date} and {end_date}."

    lines = [f"=== Earnings for {start_date} to {end_date} ==="]
    lines.append(f"Total: {total} NIS ({lesson_count} lessons)")
    lines.append(f"\n--- Per work day ---")
    for day in sorted(by_day):
        lines.append(f"  {day}: {by_day[day]} NIS")
    lines.append(f"\n--- Per student ---")
    for name, amount in sorted(by_student.items(), key=lambda x: -x[1]):
        count = sum(1 for e in events if e.get("summary") == name and e.get("colorId", "") not in _NON_LESSON_COLORS)
        lines.append(f"  {name}: {amount} NIS ({count} lessons)")

    return "\n".join(lines)


@mcp.tool()
def list_lessons(start_date: str, end_date: str) -> str:
    """Return a JSON list of lesson events in the date range.
    Each item has: student_name, date (YYYY-MM-DD), time (HH:MM), price (int).
    Only returns events with lesson colors (Lavender/Default/Flamingo).
    start_date and end_date in YYYY-MM-DD format."""
    import json
    service = _get_calendar_service()
    time_min = start_date + "T00:00:00Z"
    time_max = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d") + "T00:00:00Z"

    result = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        timeZone=TIMEZONE,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    lessons = []
    for event in result.get("items", []):
        color_id = event.get("colorId", "")
        if color_id in _NON_LESSON_COLORS:
            continue
        start = event["start"].get("dateTime", "")
        if not start:
            continue  # skip all-day events
        date_str = start[:10]
        time_str = start[11:16]
        student_name = event.get("summary", "(No title)")
        price = _get_lesson_price(student_name, color_id)
        lessons.append({
            "student_name": student_name,
            "date": date_str,
            "time": time_str,
            "price": price,
        })

    return json.dumps(lessons, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
