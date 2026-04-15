"""Structured trace logging for the Wiki QA agent.

Each query produces a JSON trace file in agent/logs/ capturing the full
conversation: messages sent, model responses, tool executions, and usage stats.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent.config import LOGS_DIR, LOG_TEXT_PREVIEW_CHARS, LOG_TOOL_RESULT_PREVIEW_CHARS


class TraceLogger:
    """Accumulates trace data for a single query and writes it to disk."""

    def __init__(self, query: str):
        self.query = query
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.turns: list[dict[str, Any]] = []
        self.start_time = time.time()
        self._current_turn: Optional[dict[str, Any]] = None
        self.error_count = 0
        self.task_completed = False
        self.tool_queries: list[str] = []
        self.tool_results_full: list[str] = []

    def start_turn(self, messages: list[dict], model: str) -> None:
        """Record the beginning of an LLM call."""
        self._current_turn = {
            "request": {
                "model": model,
                "message_count": len(messages),
                "last_message_role": messages[-1]["role"] if messages else None,
            },
            "response": {},
            "tool_executions": [],
        }

    def record_response(self, response) -> None:
        """Record the LLM response for the current turn."""
        if self._current_turn is None:
            return

        content_summary = []
        for block in response.content:
            if block.type == "thinking":
                content_summary.append({
                    "type": "thinking",
                    "thinking": block.thinking[:LOG_TEXT_PREVIEW_CHARS],
                })
            elif block.type == "text":
                content_summary.append({
                    "type": "text",
                    "text": block.text[:LOG_TEXT_PREVIEW_CHARS],
                })
            elif block.type == "tool_use":
                content_summary.append({
                    "type": "tool_use",
                    "name": block.name,
                    "input": block.input,
                })

        self._current_turn["response"] = {
            "stop_reason": response.stop_reason,
            "content": content_summary,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        }

    def record_tool_execution(
        self,
        name: str,
        tool_input: dict,
        result: str,
        duration_s: float,
        error: bool = False,
    ) -> None:
        """Record a single tool execution within the current turn."""
        if self._current_turn is None:
            return

        if error:
            self.error_count += 1

        if name == "search_wikipedia":
            self.tool_queries.append(tool_input.get("query", ""))
            self.tool_results_full.append(result)

        raw_preview = result[:LOG_TOOL_RESULT_PREVIEW_CHARS]
        if len(result) > LOG_TOOL_RESULT_PREVIEW_CHARS:
            raw_preview += "\n[...truncated in log]"

        self._current_turn["tool_executions"].append({
            "tool_name": name,
            "input": tool_input,
            "result_preview": raw_preview,
            "result_length": len(result),
            "duration_seconds": round(duration_s, 3),
            "error": error,
        })

    def record_error(self) -> None:
        """Increment the error counter for API-level failures (retried or not)."""
        self.error_count += 1

    def end_turn(self) -> None:
        """Finalize the current turn and add it to the trace."""
        if self._current_turn is not None:
            self.turns.append(self._current_turn)
            self._current_turn = None

    def finalize(self, final_answer: str, task_completed: bool = True) -> dict[str, Any]:
        """Build the complete trace dict and write it to disk."""
        self.task_completed = task_completed
        total_latency = time.time() - self.start_time

        total_input_tokens = 0
        total_output_tokens = 0
        total_tool_calls = 0
        for turn in self.turns:
            usage = turn.get("response", {}).get("usage", {})
            total_input_tokens += usage.get("input_tokens", 0)
            total_output_tokens += usage.get("output_tokens", 0)
            total_tool_calls += len(turn.get("tool_executions", []))

        trace = {
            "query": self.query,
            "timestamp": self.timestamp,
            "turns": self.turns,
            "final_answer": final_answer,
            "task_completed": self.task_completed,
            "error_count": self.error_count,
            "tool_queries": self.tool_queries,
            "tool_results_full": self.tool_results_full,
            "usage_summary": {
                "total_input_tokens": total_input_tokens,
                "total_output_tokens": total_output_tokens,
                "total_tokens": total_input_tokens + total_output_tokens,
                "tool_call_count": total_tool_calls,
                "total_latency_seconds": round(total_latency, 3),
                "llm_turns": len(self.turns),
            },
        }

        self._write_trace(trace)
        return trace

    def _write_trace(self, trace: dict) -> Path:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        filepath = LOGS_DIR / f"trace_{ts}.json"
        with open(filepath, "w") as f:
            json.dump(trace, f, indent=2, default=str)
        return filepath
