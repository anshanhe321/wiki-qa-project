#!/usr/bin/env python3
"""Interactive demo for the Wiki QA system.

Usage:
    python demo.py                    # interactive REPL
    python demo.py --demo             # run sample queries automatically
    python demo.py -q "Your question" # answer a single question
"""

import argparse
import asyncio
import sys
import textwrap

from agent.agent import run_agent
from agent.clients import close_wiki_session
from agent.config import MODEL, MAX_TURNS

DEMO_QUESTIONS = [
    "What is the capital of France?",
    "Who wrote the novel '1984'?",
    "How does photosynthesis work?",
    "Who was born first, Conan Doyle or Agatha Christie?",
    "What will the stock market do tomorrow?",
]

BANNER = r"""
╔══════════════════════════════════════════════════════════════╗
║              Wiki QA — Wikipedia Question Answering         ║
║                                                             ║
║  Ask any factual question and get an answer backed by       ║
║  Wikipedia sources, powered by Claude + MediaWiki API.      ║
╚══════════════════════════════════════════════════════════════╝
"""

HELP_TEXT = textwrap.dedent("""\
    Commands:
      Type any question to get an answer from Wikipedia.
      :demo    Run the built-in sample queries.
      :help    Show this help message.
      :quit    Exit the program.
""")


def _print_divider(char="─", width=62):
    print(char * width)


def _format_answer(trace: dict) -> None:
    """Print a formatted answer block from an agent trace."""
    summary = trace["usage_summary"]
    tool_queries = trace.get("tool_queries", [])
    final = trace.get("final_answer", "(no answer)")

    # Search info
    if tool_queries:
        print(f"\n  🔍 Wikipedia searches ({len(tool_queries)}):")
        for i, q in enumerate(tool_queries, 1):
            print(f"     {i}. \"{q}\"")
    else:
        print("\n  🔍 No Wikipedia search was needed.")

    # Answer
    print()
    _print_divider()
    print("  ANSWER:")
    _print_divider()
    wrapped = textwrap.fill(final, width=78, initial_indent="  ", subsequent_indent="  ")
    print(wrapped)
    _print_divider()

    # Stats
    print(
        f"  Model: {MODEL}  |  "
        f"Tokens: {summary['total_tokens']}  |  "
        f"Tools: {summary['tool_call_count']}  |  "
        f"LLM turns: {summary['llm_turns']}  |  "
        f"Latency: {summary['total_latency_seconds']:.1f}s"
    )
    print()


async def ask(question: str) -> None:
    """Run a single question through the agent and display results."""
    print(f"\n  Question: {question}")
    try:
        trace = await run_agent(question)
        _format_answer(trace)
    except Exception as e:
        print(f"\n  ❌ Error: {e}\n")


async def run_demo() -> None:
    """Run all sample questions sequentially."""
    print("\n  Running demo with sample questions...\n")
    for i, q in enumerate(DEMO_QUESTIONS, 1):
        print(f"  ━━━ Demo {i}/{len(DEMO_QUESTIONS)} ━━━")
        await ask(q)


async def interactive() -> None:
    """Interactive REPL loop."""
    print(BANNER)
    print(f"  Model: {MODEL}  |  Max search iterations: {MAX_TURNS}")
    print()
    print(HELP_TEXT)

    while True:
        try:
            user_input = input("  ❓ Ask > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Goodbye!\n")
            break

        if not user_input:
            continue
        if user_input.lower() in (":quit", ":exit", ":q"):
            print("  Goodbye!\n")
            break
        if user_input.lower() == ":help":
            print(HELP_TEXT)
            continue
        if user_input.lower() == ":demo":
            await run_demo()
            continue

        await ask(user_input)


async def async_main() -> None:
    parser = argparse.ArgumentParser(
        description="Wiki QA — Interactive Wikipedia Question Answering Demo"
    )
    parser.add_argument(
        "-q", "--question",
        type=str,
        default=None,
        help="Ask a single question and exit.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run built-in sample queries to demonstrate the system.",
    )
    args = parser.parse_args()

    try:
        if args.question:
            await ask(args.question)
        elif args.demo:
            print(BANNER)
            await run_demo()
        else:
            await interactive()
    finally:
        await close_wiki_session()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
