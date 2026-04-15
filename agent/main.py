"""CLI entry point for the Wiki QA agent.

Usage:
    python -m agent.main "What is the tallest building in the world?"
"""

import asyncio
import sys

from agent.agent import run_agent
from agent.clients import close_wiki_session


async def async_main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m agent.main \"<your question>\"")
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    print(f"Question: {query}\n")

    try:
        trace = await run_agent(query)
    finally:
        await close_wiki_session()

    print("=" * 60)
    print("ANSWER:")
    print("=" * 60)
    print(trace["final_answer"])
    print()

    summary = trace["usage_summary"]
    print("-" * 60)
    print("Usage Summary:")
    print(f"  Input tokens:  {summary['total_input_tokens']}")
    print(f"  Output tokens: {summary['total_output_tokens']}")
    print(f"  Total tokens:  {summary['total_tokens']}")
    print(f"  Tool calls:    {summary['tool_call_count']}")
    print(f"  LLM turns:     {summary['llm_turns']}")
    print(f"  Latency:       {summary['total_latency_seconds']:.2f}s")
    print("-" * 60)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
