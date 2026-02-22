import csv as _csv
import json
import os
import sys
import asyncio
from datetime import date
from dotenv import load_dotenv
from google import genai
from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from agents.schedule import _solve_async as schedule_solve_async
from agents.memory import load_history, append_exchange, MAX_EXCHANGES

load_dotenv()

SYSTEM_PROMPT = f"""You are a payment tracking assistant for a private teacher who teaches math, CS, and physics.
You manage a CSV file that records past lessons (student name, date, price) and their payment status.

Today's date is {date.today().isoformat()}.

## Pricing
- Default lesson price: 150 NIS
- Noam/נועם: 130 NIS
- Shoham/שוהם high school: 200 NIS

## Core Rules
1. The CSV tracks past lessons with columns: student_name, date, price, paid, payment_date.

2. MANDATORY FIRST STEP for every request: Call sync_to_csv(start_date, end_date) with the relevant date range.
   This tool fetches all lessons from the calendar, compares with the CSV, and adds all missing past lessons automatically.
   Only after calling sync_to_csv, proceed to answer the question.

3. For PAYMENT questions (who paid, who didn't pay, how much is owed, mark paid/unpaid): after sync_to_csv, read from the CSV and answer directly.

4. For EARNINGS questions (how much earned): after sync_to_csv, call query_schedule to calculate_earnings for the exact total. Respond with the EXACT numbers from the schedule agent. NEVER recalculate yourself.

5. NEVER add future lessons to the CSV — only past lessons (date < today) belong there.
6. All past lessons default to paid=yes. Only mark paid=no when the user explicitly says a student didn't pay.

## Capabilities
- Sync past lessons from calendar to CSV automatically (sync_to_csv)
- Check who paid and who didn't pay (CSV)
- Check how much money students owe (CSV)
- Mark students as paid/unpaid (update_payment)
- Calculate earnings (query_schedule → calculate_earnings)

## ReAct Reasoning Loop
You operate as a ReAct agent: Reason → Act → Observe → repeat until done.
- Before calling a tool: think about why you need it and what you expect to learn.
- After receiving results: analyze what you observed and decide what to do next.
- Continue until you have enough information to give a complete, accurate final answer."""

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WORK_MCP = os.path.join(_PROJECT_ROOT, "mcp_servers", "work_mcp.py")
_SCHEDULE_MCP = os.path.join(_PROJECT_ROOT, "mcp_servers", "schedule_mcp.py")
_CSV_PATH = os.path.join(_PROJECT_ROOT, "data", "work_ledger.csv")

_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# Load persisted history so follow-up questions have context across restarts
_persisted = load_history("work")
_history = [
    types.Content(role=h["role"], parts=[types.Part(text=h["text"])])
    for h in _persisted
]

_TYPE_MAP = {
    "string": "STRING",
    "integer": "INTEGER",
    "number": "NUMBER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
    "object": "OBJECT",
}


def _convert_schema(schema: dict) -> dict:
    """Recursively convert a JSON Schema dict to Gemini's schema format."""
    result = {"type": _TYPE_MAP.get(schema.get("type", "string"), "STRING")}
    if "description" in schema:
        result["description"] = schema["description"]
    if schema.get("type") == "array" and "items" in schema:
        result["items"] = _convert_schema(schema["items"])
    if schema.get("type") == "object" and "properties" in schema:
        result["properties"] = {
            k: _convert_schema(v) for k, v in schema["properties"].items()
        }
        if "required" in schema:
            result["required"] = schema["required"]
    return result


_SCHEDULE_TOOL_DECL = {
    "name": "query_schedule",
    "description": "Ask the schedule agent a question about calendar data (e.g. calculate earnings for a period).",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "question": {
                "type": "STRING",
                "description": "The question to ask the schedule agent",
            }
        },
        "required": ["question"],
    },
}

_SYNC_TOOL_DECL = {
    "name": "sync_to_csv",
    "description": "Fetch all lesson events from the calendar for a date range, compare with the CSV, and add any missing past lessons in one batch. Call this FIRST before answering any question.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "start_date": {"type": "STRING", "description": "Start date in YYYY-MM-DD format"},
            "end_date": {"type": "STRING", "description": "End date in YYYY-MM-DD format (use today for 'until now' queries)"},
        },
        "required": ["start_date", "end_date"],
    },
}


async def _sync_to_csv(start_date: str, end_date: str, work_session) -> str:
    """Call schedule MCP's list_lessons directly, compare with CSV in Python, add missing past lessons."""
    today = date.today().isoformat()

    # 1. Get structured lesson list from schedule MCP (no AI involved)
    schedule_params = StdioServerParameters(command=sys.executable, args=[_SCHEDULE_MCP])
    async with stdio_client(schedule_params) as (rs, ws):
        async with ClientSession(rs, ws) as schedule_session:
            await schedule_session.initialize()
            result = await schedule_session.call_tool(
                "list_lessons",
                {"start_date": start_date, "end_date": end_date},
            )
            lessons_json = result.content[0].text if result.content else "[]"

    calendar_lessons = json.loads(lessons_json)

    # 2. Filter to past lessons only
    past_lessons = [l for l in calendar_lessons if l["date"] < today]
    if not past_lessons:
        return f"No past lessons found between {start_date} and {end_date}."

    # 3. Read existing CSV slots directly in Python
    existing_slots = set()
    if os.path.exists(_CSV_PATH):
        with open(_CSV_PATH, "r") as f:
            for row in _csv.DictReader(f):
                existing_slots.add((row["date"], row["time"]))

    # 4. Find missing lessons
    missing = [
        {**l, "paid": "yes", "payment_date": ""}
        for l in past_lessons
        if (l["date"], l["time"]) not in existing_slots
    ]

    if not missing:
        return f"CSV is already up to date for {start_date} to {end_date}. ({len(past_lessons)} lessons already recorded)"

    # 5. Add all missing in one batch via work MCP
    add_result = await work_session.call_tool("add_lesson", {"lessons": missing})
    added_text = add_result.content[0].text if add_result.content else ""
    return f"Added {len(missing)} missing lessons to CSV.\n{added_text}"


def _mcp_tools_to_gemini(mcp_tools) -> list:
    """Convert MCP tool schemas into the dict format Gemini expects, plus special tools."""
    declarations = []
    for tool in mcp_tools:
        properties = {}
        required = []
        if tool.inputSchema and "properties" in tool.inputSchema:
            for name, schema in tool.inputSchema["properties"].items():
                properties[name] = _convert_schema(schema)
            required = tool.inputSchema.get("required", [])

        decl = {"name": tool.name, "description": tool.description or ""}
        if properties:
            decl["parameters"] = {
                "type": "OBJECT",
                "properties": properties,
                "required": required,
            }
        declarations.append(decl)

    declarations.append(_SCHEDULE_TOOL_DECL)
    declarations.append(_SYNC_TOOL_DECL)

    return [types.Tool(function_declarations=declarations)]


async def _solve_async(mission: str) -> str:
    """Connect to work MCP server, with schedule agent and sync tool available."""

    work_params = StdioServerParameters(command=sys.executable, args=[_WORK_MCP])

    async with stdio_client(work_params) as (r1, w1):
        async with ClientSession(r1, w1) as work_session:
            await work_session.initialize()

            work_tools = (await work_session.list_tools()).tools
            gemini_tools = _mcp_tools_to_gemini(work_tools)

            config = types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=gemini_tools,
                temperature=0.3,
            )

            contents = list(_history)
            contents.append(types.Content(role="user", parts=[types.Part(text=mission)]))

            response = _client.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents,
                config=config,
            )

            # Tool-calling loop
            while any(part.function_call for part in response.candidates[0].content.parts):
                function_calls = [
                    part.function_call
                    for part in response.candidates[0].content.parts
                    if part.function_call
                ]

                async def _execute_tool_call(fc):
                    if fc.name == "sync_to_csv":
                        return await _sync_to_csv(
                            fc.args.get("start_date", ""),
                            fc.args.get("end_date", ""),
                            work_session,
                        )
                    elif fc.name == "query_schedule":
                        question = fc.args.get("question", "")
                        return await schedule_solve_async(question)
                    else:
                        result = await work_session.call_tool(fc.name, dict(fc.args) if fc.args else {})
                        return result.content[0].text if result.content else "No result"

                results = await asyncio.gather(*(_execute_tool_call(fc) for fc in function_calls))
                function_response_parts = [
                    types.Part.from_function_response(
                        name=fc.name,
                        response={"result": text_result},
                    )
                    for fc, text_result in zip(function_calls, results)
                ]

                contents.append(response.candidates[0].content)
                contents.append(types.Content(role="user", parts=function_response_parts))

                response = _client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=contents,
                    config=config,
                )

            answer = response.text.strip()

            _history.append(types.Content(role="user", parts=[types.Part(text=mission)]))
            _history.append(response.candidates[0].content)

            max_entries = MAX_EXCHANGES * 2
            if len(_history) > max_entries:
                _history[:] = _history[-max_entries:]
            append_exchange("work", mission, answer)

            return answer


def solve(mission: str) -> str:
    """Entry point called by main.py — bridges sync world to async MCP."""
    return asyncio.run(_solve_async(mission))
