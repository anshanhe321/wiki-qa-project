"""LLM-as-a-Judge evaluation framework.

Uses Claude Opus 4.6 as an evaluator to assess:
  1. Query hallucination — whether search queries are faithful to the user question.
  2. Answer hallucination — whether the final answer is grounded in retrieved context.
  3. Semantic correctness — whether the generated answer is semantically equivalent
     to a ground-truth answer.

Each judge call returns a structured verdict with a boolean flag and reasoning.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from agent.clients import anthropic_client
from eval.config import (
    JUDGE_MAX_TOKENS,
    JUDGE_MODEL,
    JUDGE_TEMPERATURE,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_QUERY_HALLUCINATION_PROMPT = """\
<task>
You are an evaluation judge. Your job is to determine whether each search query \
in an AI agent's multi-step retrieval trajectory is faithful — i.e. every term in \
each query can be traced back to a legitimate source.

Evaluate each query using the following rules:

**Step 1 (first query):** Every term must be derivable from the user's original \
question alone. Rephrasing, synonyms, and standard search modifiers are acceptable. \
Injecting answer-level knowledge is hallucination.

**Step N (subsequent queries, N > 1):** Every term must be derivable from EITHER \
the user's original question OR entities/facts explicitly mentioned in the context \
retrieved during steps 1 through N-1. If a query introduces a term that appears \
nowhere in the user's question and nowhere in any previously retrieved context, \
that is hallucination — even if the term happens to be correct.

A query is NOT hallucinated if:
- It rephrases the user's question using synonyms or standard search terms
- It uses entity names or facts explicitly found in previously retrieved context
- It combines terms from the user's question with terms from retrieved context

A query IS hallucinated if:
- It introduces specific entities, dates, or factual claims that cannot be found \
  in either the user's question or any previously retrieved context
- It injects answer-level knowledge that the agent should not yet know at that step

Examples:
- User: "Who painted the Mona Lisa?" → Query 1: "Leonardo da Vinci paintings" → \
  HALLUCINATED (introduces "Leonardo da Vinci" from internal knowledge)
- User: "What country was the inventor of the telephone born in?" → Query 1: \
  "telephone inventor" → OK. Retrieved context mentions "Alexander Graham Bell". \
  → Query 2: "Alexander Graham Bell birthplace" → OK (entity from retrieved context)
- User: "What country was the inventor of the telephone born in?" → Query 1: \
  "Alexander Graham Bell birthplace Scotland" → HALLUCINATED (Step 1 injects \
  "Alexander Graham Bell" and "Scotland" which are not in the user's question)
</task>

<input>
<user_question>{user_question}</user_question>
<trajectory>
{trajectory}
</trajectory>
</input>

<instructions>
Evaluate each search query step-by-step against the available information at that point \
in the trajectory. Flag hallucination if ANY query introduces terms not traceable to \
the user's question or previously retrieved context.

Respond with ONLY a JSON object (no markdown, no extra text):
{{
  "hallucinated": true/false,
  "reasoning": "Brief explanation identifying which query (if any) introduced unjustified terms"
}}
</instructions>"""

_ANSWER_HALLUCINATION_PROMPT = """\
<task>
You are an evaluation judge. Your job is to determine whether the AI agent's \
final answer is grounded in the retrieved Wikipedia context.

An answer is considered **hallucinated** if it contains specific factual claims \
(dates, numbers, names, events, causal relationships) that are NOT supported by \
the provided context. The answer should be entirely derivable from the context.

Things that are NOT hallucination:
- Reasonable paraphrasing or summarization of context
- Logical inferences that directly follow from the context
- Common knowledge connective phrases ("therefore", "as a result")
- Stating that information is unavailable or uncertain

Things that ARE hallucination:
- Stating specific facts (dates, numbers, names) not present in context
- Making causal claims not supported by context
- Presenting speculation or inference as established fact
- Adding details that go beyond what the context provides
</task>

<input>
<answer>{answer}</answer>
<retrieved_context>
{context}
</retrieved_context>
</input>

<instructions>
Carefully compare every factual claim in the answer against the retrieved context. \
A single ungrounded factual claim is sufficient to flag hallucination.

Respond with ONLY a JSON object (no markdown, no extra text):
{{
  "hallucinated": true/false,
  "reasoning": "Brief explanation identifying any ungrounded claims or confirming groundedness"
}}
</instructions>"""


# ---------------------------------------------------------------------------
# Judge calls
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict[str, Any]:
    """Extract the first JSON object from text, handling extra surrounding content."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    start = text.find("{")
    if start == -1:
        raise json.JSONDecodeError("No JSON object found", text, 0)

    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])

    raise json.JSONDecodeError("Unterminated JSON object", text, start)


async def _call_judge(prompt: str) -> dict[str, Any]:
    """Send a single judge prompt and parse the JSON response."""
    try:
        response = await anthropic_client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=JUDGE_MAX_TOKENS,
            temperature=JUDGE_TEMPERATURE,
            messages=[{"role": "user", "content": prompt}],
        )

        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text

        return _extract_json(text)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Judge call failed or returned invalid JSON: %s", e)
        return {"hallucinated": False, "reasoning": f"Judge error: {e}"}


def _build_trajectory(tool_queries: list[str], tool_results: list[str]) -> str:
    """Build a step-by-step trajectory string for the query hallucination judge."""
    steps = []
    for i, query in enumerate(tool_queries):
        context = tool_results[i] if i < len(tool_results) else "(no context retrieved)"
        steps.append(
            f"<step_{i + 1}>\n"
            f"<search_query>{query}</search_query>\n"
            f"<retrieved_context>{context}</retrieved_context>\n"
            f"</step_{i + 1}>"
        )
    return "\n".join(steps)


async def judge_query_hallucination(
    user_question: str,
    tool_queries: list[str],
    tool_results: list[str],
) -> dict[str, Any]:
    """Use LLM judge to check if search queries are faithful across the trajectory.

    Evaluates every query in context: the first query must be derivable from the
    user's question alone; subsequent queries may also use entities/facts from
    previously retrieved context.

    Returns dict with 'hallucinated' (bool) and 'reasoning' (str).
    """
    if not tool_queries:
        return {"hallucinated": False, "reasoning": "No search queries were made."}

    trajectory = _build_trajectory(tool_queries, tool_results)
    prompt = _QUERY_HALLUCINATION_PROMPT.format(
        user_question=user_question,
        trajectory=trajectory,
    )
    return await _call_judge(prompt)


async def judge_answer_hallucination(
    answer: str,
    tool_results: list[str],
) -> dict[str, Any]:
    """Use LLM judge to check if the answer is grounded in retrieved context.

    Returns dict with 'hallucinated' (bool) and 'reasoning' (str).
    """
    if not answer or not tool_results:
        return {
            "hallucinated": False,
            "reasoning": "No answer or no retrieved context to evaluate.",
        }

    context = "\n---\n".join(tool_results)

    prompt = _ANSWER_HALLUCINATION_PROMPT.format(
        answer=answer,
        context=context,
    )
    return await _call_judge(prompt)


# ---------------------------------------------------------------------------
# 3. Semantic correctness
# ---------------------------------------------------------------------------

_SEMANTIC_CORRECTNESS_PROMPT = """\
<task>
You are an evaluation judge. Your job is to determine whether a generated answer \
is semantically correct by comparing it to a ground-truth answer.

The generated answer does NOT need to match the ground truth word-for-word. \
Return "correct": true as long as the generated answer captures the **core meaning** \
of the ground truth. Specifically:

- The key factual claim(s) in the ground truth must be present in the generated answer.
- Paraphrasing, additional detail, or different wording is perfectly acceptable.
- Minor differences in formatting, phrasing, or level of detail should NOT count as incorrect.
- If the ground truth is a name, date, or number, the generated answer must contain \
  that same name, date, or number (allowing for equivalent forms, e.g. "Dec 1972" = \
  "December 1972", "US" = "United States", "291" = "291 episodes").
- If the ground truth contains multiple acceptable answers separated by "/" or "or" \
  (e.g. "Moira Kelly (1994) / Beyoncé (2019)"), the generated answer is correct \
  as long as it semantically matches **at least one** of the provided options.

Examples:
- Ground truth: "Marie Curie" / Generated: "The element was discovered by Marie \
  Curie, a Polish-French physicist" → correct (core fact present)
- Ground truth: "1969" / Generated: "The moon landing occurred on July 20, 1969" → correct
- Ground truth: "6,371 km" / Generated: "Earth's mean radius is approximately \
  6,371 kilometers" → correct (equivalent form)
- Ground truth: "Charles Darwin" / Generated: "The theory was proposed by Isaac \
  Newton" → incorrect (wrong person)
- Ground truth: "Tokyo / Edo" / Generated: "The city was historically known as \
  Edo" → correct (matches at least one option)
</task>

<input>
<ground_truth>{expected}</ground_truth>
<generated_answer>{answer}</generated_answer>
</input>

<instructions>
Determine whether the generated answer is semantically correct — i.e. it conveys \
the same core factual content as the ground truth. If the ground truth lists multiple \
acceptable answers, the generated answer only needs to match at least one of them.

Respond with ONLY a JSON object (no markdown, no extra text):
{{
  "correct": true/false,
  "reasoning": "Brief explanation of your judgment"
}}
</instructions>"""


async def judge_semantic_correctness(
    answer: str,
    expected_answer: str,
) -> dict[str, Any]:
    """Use LLM judge to check if the answer is semantically correct vs ground truth.

    Returns dict with 'correct' (bool) and 'reasoning' (str).
    Returns None-like verdict when there is no expected answer to compare against.
    """
    if not expected_answer:
        return {"correct": None, "reasoning": "No ground-truth answer to compare against."}
    if not answer:
        return {"correct": False, "reasoning": "No generated answer to evaluate."}

    prompt = _SEMANTIC_CORRECTNESS_PROMPT.format(
        expected=expected_answer,
        answer=answer,
    )
    return await _call_judge(prompt)
