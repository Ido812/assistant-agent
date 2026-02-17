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

## Identifying lessons from calendar events
- Default color and Lavender color = private lessons (150 NIS, except Noam=130)
- Flamingo color = Shoham high school lesson (200 NIS)
- These colors are NEVER lessons: Grape (trainings), Sage (fun/social), Banana, Tomato, Peacock, Basil
- Extract the student name from the event title

## Core Rules
1. The CSV tracks past lessons with columns: student_name, date, price, paid, payment_date.
2. For PAYMENT questions (who paid, who didn't pay, mark paid/unpaid, how much money is owed): go DIRECTLY to the CSV. No calendar query needed.
3. For EARNINGS questions (how much earned, how much will earn): use query_schedule to ask the schedule agent to calculate earnings. After getting the answer, sync any missing PAST lessons to the CSV via add_lesson, then respond with the EXACT numbers from the schedule agent's response. NEVER recalculate or reinterpret the totals — forward them exactly as given.
4. For LESSON SYNC (populating/updating the CSV with new lessons): use query_schedule to get lesson data from the calendar, then add any missing PAST lessons to the CSV via add_lesson.
5. NEVER add future lessons to the CSV — only past lessons belong there.
6. Determine the price based on the student name (Noam/נועם=130, Shoham/שוהם=200, all others=150).
7. All past lessons default to paid=yes. Only mark paid=no when the user explicitly says a student didn't pay.

## Capabilities
- Check who paid and who didn't pay (directly from CSV)
- Check how much money students owe (unpaid lessons from CSV)
- Mark students as paid/unpaid via update_payment
- Calculate earnings via the schedule agent (which reads from the calendar)
- Sync past lessons from calendar to CSV"""

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WORK_MCP = os.path.join(_PROJECT_ROOT, "mcp_servers", "work_mcp.py")

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

# Extra tool declaration for querying the schedule agent
_SCHEDULE_TOOL_DECL = {
    "name": "query_schedule",
    "description": "Ask the schedule agent a question to retrieve calendar/lesson data. Use this when the CSV doesn't have the data you need.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "question": {
                "type": "STRING",
                "description": "The question to ask the schedule agent, e.g. 'List all lessons between 2026-02-01 and 2026-02-28'",
            }
        },
        "required": ["question"],
    },
}


def _mcp_tools_to_gemini(mcp_tools) -> list:
    """Convert MCP tool schemas into the dict format Gemini expects, plus the schedule query tool."""
    declarations = []
    for tool in mcp_tools:
        properties = {}
        required = []
        if tool.inputSchema and "properties" in tool.inputSchema:
            for name, schema in tool.inputSchema["properties"].items():
                prop_type = _TYPE_MAP.get(schema.get("type", "string"), "STRING")
                properties[name] = {
                    "type": prop_type,
                    "description": schema.get("description", ""),
                }
            required = tool.inputSchema.get("required", [])

        decl = {"name": tool.name, "description": tool.description or ""}
        if properties:
            decl["parameters"] = {
                "type": "OBJECT",
                "properties": properties,
                "required": required,
            }
        declarations.append(decl)

    # Add the schedule query tool
    declarations.append(_SCHEDULE_TOOL_DECL)

    return [types.Tool(function_declarations=declarations)]


async def _solve_async(mission: str) -> str:
    """Connect to work MCP server, with schedule agent available as a tool."""

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
            while response.candidates[0].content.parts[0].function_call:
                function_calls = [
                    part.function_call
                    for part in response.candidates[0].content.parts
                    if part.function_call
                ]

                async def _execute_tool_call(fc):
                    if fc.name == "query_schedule":
                        question = fc.args.get("question", "")
                        return await schedule_solve_async(question)
                    else:
                        result = await work_session.call_tool(fc.name, dict(fc.args) if fc.args else {})
                        return result.content[0].text if result.content else "No result"

                # Execute all tool calls in parallel
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

            # Trim in-memory history and persist to disk
            max_entries = MAX_EXCHANGES * 2
            if len(_history) > max_entries:
                _history[:] = _history[-max_entries:]
            append_exchange("work", mission, answer)

            return answer


def solve(mission: str) -> str:
    """Entry point called by main.py — bridges sync world to async MCP."""
    return asyncio.run(_solve_async(mission))
