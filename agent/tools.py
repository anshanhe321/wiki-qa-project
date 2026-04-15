"""Tool definitions and dispatch for the Wiki QA agent."""

from agent.wikipedia_client import search_wikipedia

TOOLS = [
    {
        "name": "search_wikipedia",
        "description": (
            "Search Wikipedia and return relevant article extracts. "
            "Supports three usage patterns: "
            "(1) a single search for straightforward factual lookups, "
            "(2) multiple parallel searches issued at once to gather information "
            "from different topics simultaneously, and "
            "(3) iterative sequential searches where later queries are refined "
            "based on entities or facts discovered in earlier results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "A keyword-based search query composed of core concepts, "
                        "named entities, and specific nouns. Do NOT write full "
                        "natural-language sentences. Example: for 'When was the "
                        "Eiffel Tower built?', use 'Eiffel Tower' "
                        "rather than 'When was the Eiffel Tower built'."
                    ),
                }
            },
            "required": ["query"],
        },
    }
]


async def dispatch_tool(name: str, tool_input: dict) -> str:
    """Execute a tool by name and return its string result."""
    if name == "search_wikipedia":
        query = tool_input.get("query", "")
        return await search_wikipedia(query)
    raise ValueError(f"Unknown tool: {name}")
