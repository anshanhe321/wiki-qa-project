"""Metrics extraction and cost calculation for the Wiki QA eval suite.

Reads structured trace dicts produced by the agent and derives system-level
metrics: token counts, latency, tool-call frequency, estimated USD cost,
task completion, error counts, recall, and hallucination checks.

Hallucination detection uses an LLM-as-a-Judge framework (Claude Opus 4.6)
with heuristic-based fallbacks.
"""

from __future__ import annotations

import asyncio
import logging
import string
from typing import Any, Optional

from eval.config import INPUT_COST_PER_TOKEN, OUTPUT_COST_PER_TOKEN
from eval.llm_judge import (
    judge_answer_hallucination,
    judge_query_hallucination,
    judge_semantic_correctness,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core system metrics (from trace)
# ---------------------------------------------------------------------------

async def extract_metrics(
    trace: dict[str, Any],
    expected_answer: Optional[str] = None,
) -> dict[str, Any]:
    """Pull system metrics out of a single agent trace.

    Returns a flat dict suitable for tabular display and JSON serialization.
    Hallucination checks are performed by an LLM judge (async).
    """
    summary = trace.get("usage_summary", {})

    input_tokens = summary.get("total_input_tokens", 0)
    output_tokens = summary.get("total_output_tokens", 0)
    total_tokens = summary.get("total_tokens", 0)
    tool_call_count = summary.get("tool_call_count", 0)
    latency = summary.get("total_latency_seconds", 0.0)
    llm_turns = summary.get("llm_turns", 0)

    cost = (input_tokens * INPUT_COST_PER_TOKEN) + (output_tokens * OUTPUT_COST_PER_TOKEN)

    task_completed = trace.get("task_completed", False)
    error_count = trace.get("error_count", 0)
    recall = compute_recall(trace.get("final_answer", ""), expected_answer)

    user_question = trace.get("query", "")
    tool_queries = trace.get("tool_queries", [])
    final_answer = trace.get("final_answer", "")
    tool_results = trace.get("tool_results_full", [])

    q_judge_task = judge_query_hallucination(user_question, tool_queries, tool_results)
    a_judge_task = judge_answer_hallucination(final_answer, tool_results)
    s_judge_task = judge_semantic_correctness(final_answer, expected_answer)
    q_verdict, a_verdict, s_verdict = await asyncio.gather(
        q_judge_task, a_judge_task, s_judge_task,
    )

    has_citation = check_citation(final_answer) if tool_call_count > 0 else None

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "tool_call_count": tool_call_count,
        "llm_turns": llm_turns,
        "latency_seconds": round(latency, 3),
        "cost_usd": round(cost, 6),
        "task_completed": task_completed,
        "error_count": error_count,
        "recall": recall,
        "has_citation": has_citation,
        "semantic_correctness": s_verdict.get("correct"),
        "semantic_correctness_reasoning": s_verdict.get("reasoning", ""),
        "query_hallucination": q_verdict.get("hallucinated", False),
        "query_hallucination_reasoning": q_verdict.get("reasoning", ""),
        "answer_hallucination": a_verdict.get("hallucinated", False),
        "answer_hallucination_reasoning": a_verdict.get("reasoning", ""),
    }


# ---------------------------------------------------------------------------
# 3. Recall score
# ---------------------------------------------------------------------------

def _normalize(text: str) -> set[str]:
    """Lowercase, strip punctuation, and tokenize into a set of words."""
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    return {w for w in text.split() if len(w) > 1}


def compute_recall(answer: str, expected: Optional[str]) -> Optional[float]:
    """Measure whether the generated answer covers key terms from the expected answer.

    Returns the fraction of expected-answer tokens found in the generated answer,
    or None when there is no expected answer to compare against.
    """
    if not expected:
        return None

    expected_tokens = _normalize(expected)
    if not expected_tokens:
        return None

    answer_tokens = _normalize(answer)
    hits = expected_tokens & answer_tokens
    return round(len(hits) / len(expected_tokens), 3)


# ---------------------------------------------------------------------------
# Citation check (rule-based)
# ---------------------------------------------------------------------------

def check_citation(answer: str) -> bool:
    """Check whether the answer includes a citation via exact substring match."""
    return "Source:" in answer or "Sources:" in answer


# ---------------------------------------------------------------------------
# Hallucination detection is handled by the LLM-as-a-Judge framework
# in eval/llm_judge.py (called from extract_metrics above).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

_SUMMABLE_KEYS = {
    "input_tokens", "output_tokens", "total_tokens", "tool_call_count",
    "llm_turns", "latency_seconds", "cost_usd", "error_count",
}


def aggregate_metrics(per_query: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate stats across a list of per-query metric dicts."""
    n = len(per_query)
    if n == 0:
        return {}

    totals: dict[str, float] = {}
    for m in per_query:
        for k in _SUMMABLE_KEYS:
            totals[k] = totals.get(k, 0.0) + m.get(k, 0)

    completed = sum(1 for m in per_query if m.get("task_completed"))
    recall_vals = [m["recall"] for m in per_query if m.get("recall") is not None]
    query_hal = sum(1 for m in per_query if m.get("query_hallucination"))
    answer_hal = sum(1 for m in per_query if m.get("answer_hallucination"))

    sem_correct_vals = [
        m["semantic_correctness"]
        for m in per_query
        if m.get("semantic_correctness") is not None
    ]
    sem_correct_count = sum(1 for v in sem_correct_vals if v)
    sem_total = len(sem_correct_vals)

    cite_vals = [
        m["has_citation"]
        for m in per_query
        if m.get("has_citation") is not None
    ]
    cite_count = sum(1 for v in cite_vals if v)
    cite_total = len(cite_vals)

    return {
        "num_queries": n,
        "total_input_tokens": int(totals.get("input_tokens", 0)),
        "total_output_tokens": int(totals.get("output_tokens", 0)),
        "total_tokens": int(totals.get("total_tokens", 0)),
        "total_tool_calls": int(totals.get("tool_call_count", 0)),
        "total_cost_usd": round(totals.get("cost_usd", 0.0), 6),
        "total_errors": int(totals.get("error_count", 0)),
        "avg_latency_seconds": round(totals.get("latency_seconds", 0.0) / n, 3),
        "avg_tokens_per_query": round(totals.get("total_tokens", 0) / n, 1),
        "avg_tool_calls_per_query": round(totals.get("tool_call_count", 0) / n, 2),
        "avg_cost_per_query_usd": round(totals.get("cost_usd", 0.0) / n, 6),
        "task_completion_rate": round(completed / n, 3),
        "avg_recall": round(sum(recall_vals) / len(recall_vals), 3) if recall_vals else None,
        "semantic_correctness_rate": round(sem_correct_count / sem_total, 3) if sem_total else None,
        "semantic_correct_count": sem_correct_count,
        "semantic_evaluated_count": sem_total,
        "citation_count": cite_count,
        "citation_evaluated_count": cite_total,
        "citation_rate": round(cite_count / cite_total, 3) if cite_total else None,
        "query_hallucination_count": query_hal,
        "answer_hallucination_count": answer_hal,
    }
