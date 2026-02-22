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

SYSTEM_PROMPT = """You are a stock market analyst assistant.
You help the user analyze stocks, make sense of market data, and answer investing questions.
Use the available tools to fetch real-time stock data when needed.
Keep your answers clear, data-driven, and concise.

## ReAct Reasoning Loop
You operate as a ReAct agent: Reason → Act → Observe → repeat until done.
- Before calling a tool: think about why you need it and what you expect to learn.
- After receiving results: analyze what you observed and decide what to do next.
- Continue until you have enough information to give a complete, accurate final answer."""

# Full path to the MCP server so it works from any working directory
_MCP_SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp_servers", "stock_mcp.py")

_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# Load persisted history so follow-up questions have context across restarts
_persisted = load_history("stock")
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

    # Launch stock_mcp.py as a subprocess and connect via stdio
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
            while any(part.function_call for part in response.candidates[0].content.parts):
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
                function_response_parts = [
                    types.Part.from_function_response(
                        name=fc.name,
                        response={"result": result.content[0].text if result.content else "No result"},
                    )
                    for fc, result in zip(function_calls, results)
                ]

                # Feed the model's call + tool results back into the conversation
                contents.append(response.candidates[0].content)
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
            append_exchange("stock", mission, answer)

            return answer


def solve(mission: str) -> str:
    """Entry point called by main.py — bridges sync world to async MCP."""
    return asyncio.run(_solve_async(mission))
