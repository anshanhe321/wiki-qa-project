"""Core async agent event loop for the Wiki QA system.

Handles the full cycle: receiving a prompt, calling the LLM with tools,
executing tool calls, feeding results back, and returning the final answer.
Includes exponential-backoff retry for Anthropic API calls.
"""

import asyncio
import logging
import time
from typing import Any

import anthropic

from agent.clients import anthropic_client
from agent.config import (
    MAX_RETRIES,
    MAX_TOKENS,
    MAX_TURNS,
    MODEL,
    RETRY_BASE_DELAY,
    RETRY_MAX_DELAY,
    TEMPERATURE,
)
from agent.logger import TraceLogger
from agent.prompts import SYSTEM_PROMPT
from agent.tools import TOOLS, dispatch_tool

logger = logging.getLogger(__name__)


async def _call_llm(messages: list[dict], trace_logger: TraceLogger) -> Any:
    """Call the Anthropic messages API with retry on rate-limit / transient errors."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await anthropic_client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )
        except (
            anthropic.RateLimitError,
            anthropic.InternalServerError,
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
        ) as e:
            trace_logger.record_error()
            if attempt == MAX_RETRIES:
                logger.error("LLM call failed after %d attempts: %s", MAX_RETRIES, e)
                raise
            delay = min(RETRY_BASE_DELAY * (2 ** (attempt - 1)), RETRY_MAX_DELAY)
            logger.warning(
                "LLM attempt %d/%d failed (%s), retrying in %.1fs",
                attempt, MAX_RETRIES, e, delay,
            )
            await asyncio.sleep(delay)

    raise RuntimeError("Unreachable")


async def run_agent(query: str) -> dict[str, Any]:
    """Run the agent on a single query and return the full trace.

    Returns a trace dict containing the query, all turns, the final answer,
    and a usage summary. The trace is also written to disk by the logger.
    """
    trace_logger = TraceLogger(query)
    messages: list[dict] = [{"role": "user", "content": query}]
    final_answer = ""
    task_completed = False

    for turn_idx in range(MAX_TURNS):
        trace_logger.start_turn(messages, MODEL)

        response = await _call_llm(messages, trace_logger)

        trace_logger.record_response(response)

        if response.stop_reason == "end_turn":
            for block in response.content:
                if block.type == "text":
                    final_answer += block.text
            trace_logger.end_turn()
            task_completed = True
            break

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                t0 = time.time()
                tool_error = False
                try:
                    result = await dispatch_tool(block.name, block.input)
                except Exception as e:
                    result = f"Tool error: {e}"
                    tool_error = True
                duration = time.time() - t0

                trace_logger.record_tool_execution(
                    block.name, block.input, result, duration, error=tool_error
                )

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

            messages.append({"role": "user", "content": tool_results})
            trace_logger.end_turn()
        else:
            for block in response.content:
                if block.type == "text":
                    final_answer += block.text
            trace_logger.end_turn()
            task_completed = True
            break

    trace = trace_logger.finalize(final_answer, task_completed=task_completed)
    return trace
