"""Eval runner for the Wiki QA system.

Loads test cases, runs each through the agent concurrently (bounded by a
semaphore), collects system metrics, and writes a timestamped report.

Usage:
    python -m eval.eval_runner                  # run all test cases
    python -m eval.eval_runner --cases q1,q3    # run a subset
    python -m eval.eval_runner --golden         # use golden test set
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from tabulate import tabulate

from agent.agent import run_agent
from agent.clients import close_wiki_session
from agent.config import EVAL_CONCURRENCY
from eval.config import GOLDEN_TEST_CASES_PATH, RESULTS_DIR, TEST_CASES_PATH
from eval.metrics import aggregate_metrics, extract_metrics


def load_test_cases(
    filter_ids: Optional[list[str]] = None,
    golden: bool = False,
) -> list[dict]:
    path = GOLDEN_TEST_CASES_PATH if golden else TEST_CASES_PATH
    with open(path) as f:
        cases = json.load(f)
    if filter_ids:
        cases = [c for c in cases if c["id"] in filter_ids]
    return cases


async def _run_single(
    case: dict, index: int, total: int, sem: asyncio.Semaphore,
) -> dict[str, Any]:
    """Run a single test case, respecting the concurrency semaphore."""
    qid = case["id"]
    question = case["question"]
    expected = case.get("expected_answer")

    async with sem:
        print(f"[{index}/{total}] Running {qid}: {question}")
        try:
            trace = await run_agent(question)
            metrics = await extract_metrics(trace, expected_answer=expected)
            sem_str = {True: "Y", False: "N", None: "-"}.get(
                metrics["semantic_correctness"], "-"
            )
            cite_str = {True: "Y", False: "N", None: "-"}.get(
                metrics["has_citation"], "-"
            )
            print(
                f"  -> OK  ({metrics['latency_seconds']:.1f}s, "
                f"{metrics['total_tokens']} tok, "
                f"recall={metrics['recall']}, "
                f"sem={sem_str}, "
                f"cite={cite_str}, "
                f"q_hal={metrics['query_hallucination']}, "
                f"a_hal={metrics['answer_hallucination']})"
            )
            return {
                "input": {
                    "id": qid,
                    "category": case.get("category", ""),
                    "source": case.get("source", ""),
                    "question": question,
                    "expected_answer": expected,
                    "notes": case.get("notes"),
                },
                "trace": {
                    "turns": trace.get("turns", []),
                    "tool_queries": trace.get("tool_queries", []),
                    "tool_results_full": trace.get("tool_results_full", []),
                    "task_completed": trace.get("task_completed", False),
                    "error_count": trace.get("error_count", 0),
                    "final_answer": trace.get("final_answer", ""),
                },
                "metrics": metrics,
                "status": "success",
            }
        except Exception as e:
            print(f"  -> FAILED: {e}")
            return {
                "input": {
                    "id": qid,
                    "category": case.get("category", ""),
                    "source": case.get("source", ""),
                    "question": question,
                    "expected_answer": expected,
                    "notes": case.get("notes"),
                },
                "trace": None,
                "metrics": None,
                "status": f"error: {e}",
            }


async def run_eval(cases: list[dict]) -> dict[str, Any]:
    """Run all test cases concurrently and return the full eval report."""
    sem = asyncio.Semaphore(EVAL_CONCURRENCY)

    tasks = [
        _run_single(case, i, len(cases), sem)
        for i, case in enumerate(cases, 1)
    ]
    results = await asyncio.gather(*tasks)

    per_query_metrics = [r["metrics"] for r in results if r["metrics"]]
    summary = aggregate_metrics(per_query_metrics)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "num_cases": len(cases),
        "results": list(results),
        "summary": summary,
    }


def print_summary(report: dict[str, Any]) -> None:
    """Print a human-readable summary table to stdout."""
    rows = []
    for r in report["results"]:
        qid = r.get("input", {}).get("id", "?")
        if r["metrics"]:
            m = r["metrics"]
            recall_str = f"{m['recall']:.2f}" if m["recall"] is not None else "-"
            sem_val = m.get("semantic_correctness")
            sem_str = {True: "Y", False: "N", None: "-"}.get(sem_val, "-")
            rows.append([
                qid,
                "Y" if m["task_completed"] else "N",
                m["error_count"],
                m["total_tokens"],
                m["tool_call_count"],
                f"{m['latency_seconds']:.1f}s",
                f"${m['cost_usd']:.4f}",
                recall_str,
                sem_str,
                {True: "Y", False: "N", None: "-"}.get(m.get("has_citation"), "-"),
                "Y" if m["query_hallucination"] else "N",
                "Y" if m["answer_hallucination"] else "N",
            ])
        else:
            rows.append([qid, "N", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-"])

    headers = [
        "ID", "Done", "Errs", "Tokens", "Tools",
        "Latency", "Cost", "Recall", "Sem", "Cite", "Q-Hal", "A-Hal",
    ]
    print("\n" + tabulate(rows, headers=headers, tablefmt="grid"))

    s = report.get("summary", {})
    if s:
        print(f"\nAggregate ({s.get('num_queries', 0)} queries):")
        print(f"  Task completion rate:   {s.get('task_completion_rate', 0):.1%}")
        print(f"  Total errors:           {s.get('total_errors', 0)}")
        print(f"  Total tokens:           {s.get('total_tokens', 0)}")
        print(f"  Total cost:             ${s.get('total_cost_usd', 0):.4f}")
        print(f"  Avg latency:            {s.get('avg_latency_seconds', 0):.1f}s")
        print(f"  Avg tokens/query:       {s.get('avg_tokens_per_query', 0):.0f}")
        print(f"  Avg tool calls/query:   {s.get('avg_tool_calls_per_query', 0):.1f}")
        print(f"  Avg cost/query:         ${s.get('avg_cost_per_query_usd', 0):.4f}")
        avg_recall = s.get("avg_recall")
        print(f"  Avg recall:             {avg_recall:.3f}" if avg_recall is not None else "  Avg recall:             -")
        sem_rate = s.get("semantic_correctness_rate")
        sem_n = s.get("semantic_evaluated_count", 0)
        sem_c = s.get("semantic_correct_count", 0)
        if sem_rate is not None:
            print(f"  Semantic correctness:   {sem_c}/{sem_n} ({sem_rate:.1%})")
        else:
            print(f"  Semantic correctness:   -")
        cite_n = s.get("citation_count", 0)
        cite_total = s.get("citation_evaluated_count", 0)
        cite_r = s.get("citation_rate")
        if cite_r is not None:
            print(f"  Citation rate:          {cite_n}/{cite_total} ({cite_r:.1%})")
        else:
            print(f"  Citation rate:          -")
        print(f"  Query hallucinations:   {s.get('query_hallucination_count', 0)}")
        print(f"  Answer hallucinations:  {s.get('answer_hallucination_count', 0)}")


def save_report(report: dict[str, Any]) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filepath = RESULTS_DIR / f"eval_{ts}.json"
    with open(filepath, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nReport saved to {filepath}")
    return filepath


async def async_main() -> None:
    parser = argparse.ArgumentParser(description="Run Wiki QA eval suite")
    parser.add_argument(
        "--cases",
        type=str,
        default=None,
        help="Comma-separated list of case IDs to run (e.g. q1,q3). Default: all.",
    )
    parser.add_argument(
        "--golden",
        action="store_true",
        help="Use the golden test set (golden_test_cases.json) instead of the default.",
    )
    args = parser.parse_args()

    filter_ids = args.cases.split(",") if args.cases else None
    cases = load_test_cases(filter_ids, golden=args.golden)

    if not cases:
        print("No test cases found.")
        sys.exit(1)

    print(f"Running {len(cases)} test case(s) (concurrency={EVAL_CONCURRENCY})...\n")

    try:
        report = await run_eval(cases)
    finally:
        await close_wiki_session()

    print_summary(report)
    save_report(report)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
