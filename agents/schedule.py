import os
import sys
import asyncio
from dotenv import load_dotenv
from google import genai
from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from agents.memory import load_history, append_exchange, MAX_EXCHANGES

load_dotenv()

from datetime import date

SYSTEM_PROMPT = f"""You are a calendar, scheduling, and earnings assistant for a private teacher (math, CS, physics).
You help manage Google Calendar events and calculate lesson earnings.

Today's date is {date.today().isoformat()}.

## Calendar Management

Default event colors (always apply unless the user specifies otherwise):
- Private lessons/classes: color_id=1 (Lavender)
- Classes at Shoham high school: color_id=4 (Flamingo)
- Trainings/workouts: color_id=3 (Grape)
- Fun/leisure/social: color_id=2 (Sage)

All available colors: 1=Lavender, 2=Sage, 3=Grape, 4=Flamingo, 5=Banana,
6=Tangerine, 7=Peacock, 8=Graphite, 9=Blueberry, 10=Basil, 11=Tomato

Guidelines:
- When the user asks to see their schedule, use list_events with the appropriate date range.
- When deleting or updating events, first list events to find the correct event ID.
- For recurring events, use the recurrence parameter with an RRULE string.
- Format dates and times clearly for the user.
- The user's timezone is Asia/Jerusalem.

## Earnings Calculation

Pricing rules:
- Default lesson price: 150 NIS
- Noam/נועם: 130 NIS
- Shoham/שוהם high school: 200 NIS

Lesson identification by color:
- Default color and Lavender = private lessons (150 NIS, except Noam=130)
- Flamingo = Shoham high school lesson (200 NIS)
- These colors are NEVER lessons: Grape, Sage, Banana, Tomato, Peacock, Basil

For any earnings/money questions, ALWAYS use the calculate_earnings tool. NEVER do arithmetic yourself.

## ReAct Reasoning Loop
You operate as a ReAct agent: Reason → Act → Observe → repeat until done.
- Before calling a tool: think about why you need it and what you expect to learn.
- After receiving results: analyze what you observed and decide what to do next.
- Continue until you have enough information to give a complete, accurate final answer.

## Retry Policy — CRITICAL
If a tool call returns an ❌ ERROR, you MUST NOT report failure to the user.
Instead:
1. Analyze what went wrong (wrong event ID? bad date format? stale data?)
2. Fix the issue (e.g. call list_events again to get fresh event IDs)
3. Retry the failed operation with corrected parameters
Only stop retrying if the same error repeats 3+ times with no progress."""

# Full path to the MCP server so it works from any working directory
_MCP_SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp_servers", "schedule_mcp.py")

_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# Load persisted history so follow-up questions have context across restarts
_persisted = load_history("schedule")
_history = [
    types.Content(role=h["role"], parts=[types.Part(text=h["text"])])
    for h in _persisted
]

# JSON Schema type -> Gemini Schema type
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


def _mcp_tools_to_gemini(mcp_tools) -> list:
    """Convert MCP tool schemas into the dict format Gemini expects."""
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
    return [types.Tool(function_declarations=declarations)]


async def _solve_async(mission: str) -> str:
    """Core async logic: connect to MCP, let Gemini call tools, return answer."""

    # Launch schedule_mcp.py as a subprocess and connect via stdio
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[_MCP_SERVER],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Discover available tools from the MCP server
            tools_result = await session.list_tools()
            gemini_tools = _mcp_tools_to_gemini(tools_result.tools)

            config = types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=gemini_tools,
                temperature=0.3,
            )

            # Start from previous conversation + new user message
            contents = list(_history)
            contents.append(types.Content(role="user", parts=[types.Part(text=mission)]))

            response = _client.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents,
                config=config,
            )

            # Function calling loop: Gemini may request tool calls before answering
            MAX_TOOL_ITERATIONS = 10
            iteration = 0

            while any(part.function_call for part in response.candidates[0].content.parts):
                iteration += 1
                if iteration > MAX_TOOL_ITERATIONS:
                    break

                # Gather every tool call from the response
                function_calls = [
                    part.function_call
                    for part in response.candidates[0].content.parts
                    if part.function_call
                ]

                # Execute all tool calls in parallel through the MCP server
                results = await asyncio.gather(*(
                    session.call_tool(fc.name, dict(fc.args) if fc.args else {})
                    for fc in function_calls
                ))

                # Extract result text for each tool call
                result_texts = [
                    result.content[0].text if result.content else "No result"
                    for result in results
                ]

                function_response_parts = [
                    types.Part.from_function_response(
                        name=fc.name,
                        response={"result": text},
                    )
                    for fc, text in zip(function_calls, result_texts)
                ]

                # Check if any tool call failed
                has_errors = any("❌ ERROR" in text for text in result_texts)

                # Feed the model's call + tool results back into the conversation
                contents.append(response.candidates[0].content)

                if has_errors:
                    # Inject a retry nudge so Gemini fixes and retries instead of giving up
                    retry_nudge = types.Part(text=(
                        "⚠️ One or more tool calls above returned ❌ ERROR. "
                        "Do NOT give up or report failure to the user. "
                        "Analyze the error, fix the issue (re-list events if IDs may be "
                        "stale, correct the date/time format, etc.), and retry the failed operation."
                    ))
                    contents.append(types.Content(role="user", parts=function_response_parts + [retry_nudge]))
                else:
                    contents.append(types.Content(role="user", parts=function_response_parts))

                # Let Gemini process the tool results (may call more tools or answer)
                response = _client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=contents,
                    config=config,
                )

            answer = response.text.strip()

            # Save this exchange so future calls remember the conversation
            _history.append(types.Content(role="user", parts=[types.Part(text=mission)]))
            _history.append(response.candidates[0].content)

            # Trim in-memory history and persist to disk
            max_entries = MAX_EXCHANGES * 2
            if len(_history) > max_entries:
                _history[:] = _history[-max_entries:]
            append_exchange("schedule", mission, answer)

            return answer


def solve(mission: str) -> str:
    """Entry point called by main.py — bridges sync world to async MCP."""
    return asyncio.run(_solve_async(mission))
