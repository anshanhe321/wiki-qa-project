# Wiki QA System -- Design & Architecture

A question-answering system that uses the Anthropic API and Wikipedia to answer factual questions, paired with a comprehensive evaluation suite featuring LLM-as-a-Judge metrics for hallucination detection, semantic correctness, and citation verification.

## Project Structure

```
wiki_qa_project/
├── .env                           # ANTHROPIC_API_KEY (not committed)
├── .gitignore                     # excludes .env, __pycache__, bulk logs/results
├── README.md                      # setup instructions & quick start
├── DESIGN.md                      # this file
├── demo.py                        # interactive demo CLI (REPL, --demo, -q modes)
│
├── agent/                         # the QA agent package
│   ├── __init__.py
│   ├── config.py                  # all tunable constants
│   ├── prompts.py                 # XML-structured system prompt
│   ├── clients.py                 # async Anthropic + Wikipedia clients (singletons)
│   ├── wikipedia_client.py        # two-phase MediaWiki retrieval
│   ├── tools.py                   # tool schema + dispatch
│   ├── agent.py                   # core event loop (async, with retry)
│   ├── logger.py                  # structured JSON trace logging
│   ├── main.py                    # CLI entry point (single query)
│   ├── requirements.txt           # anthropic, aiohttp, python-dotenv
│   └── logs/                      # auto-created; one JSON trace per query
│
└── eval/                          # the evaluation suite
    ├── __init__.py
    ├── config.py                  # eval-specific constants (paths, pricing, judge)
    ├── test_cases.json            # seed questions (5)
    ├── golden_test_cases.json     # comprehensive test set (30 questions)
    ├── metrics.py                 # per-query metric extraction + aggregation
    ├── llm_judge.py               # LLM-as-a-Judge (hallucination + correctness)
    ├── eval_runner.py             # concurrent test runner with summary table
    ├── requirements.txt           # tabulate
    └── results/                   # auto-created; timestamped eval reports
```

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│  demo.py / main.py / eval_runner.py                              │
│  (entry points -- asyncio.run)                                   │
└──────────────┬───────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────┐
│  agent.py  --  async event loop                                  │
│                                                                  │
│  1. Send user query + system prompt + tool defs to Claude        │
│  2. If stop_reason == "tool_use":                                │
│       extract tool_use blocks                                    │
│       execute via dispatch_tool()                                │
│       append tool_result messages                                │
│       loop back to step 1                                        │
│  3. If stop_reason == "end_turn":                                │
│       extract final text answer                                  │
│  4. Write trace log, return trace dict                           │
│                                                                  │
│  LLM calls retry on: RateLimitError, InternalServerError,        │
│  APIConnectionError, APITimeoutError                             │
└─────┬──────────────────────┬─────────────────────────────────────┘
      │                      │
      ▼                      ▼
┌────────────┐    ┌──────────────────────────────────────────────┐
│  tools.py  │    │  logger.py (TraceLogger)                     │
│            │    │                                              │
│  TOOLS     │    │  per-turn: request summary, response,        │
│  schema    │    │  tool executions (name, input, result        │
│            │    │  preview, duration, error flag)               │
│  dispatch  │    │                                              │
│  _tool()   │    │  also captures: error_count, task_completed, │
│            │    │  tool_queries, tool_results_full              │
│            │    │                                              │
│            │    │  finalize: writes JSON to agent/logs/         │
└─────┬──────┘    └──────────────────────────────────────────────┘
      │
      ▼
┌──────────────────────────────────────────────────────────────────┐
│  wikipedia_client.py                                             │
│                                                                  │
│  Phase 1: action=query, list=search  -->  top 3 page titles      │
│  Phase 2: action=query, prop=extracts, explaintext=1             │
│           --> fetch each article individually & concurrently     │
│           --> intro-section fallback for oversized articles      │
│           --> plain-text content (truncated to 6000 chars each)  │
│                                                                  │
│  Calls go through clients.wiki_get() (aiohttp + retry)           │
└──────────────────────────────────────────────────────────────────┘

── Eval flow ──────────────────────────────────────────────────────

┌──────────────────────────────────────────────────────────────────┐
│  eval_runner.py                                                  │
│                                                                  │
│  1. Load test cases (basic or --golden)                          │
│  2. Run each through agent concurrently (semaphore-bounded)      │
│  3. Extract system + quality metrics per query                   │
│  4. Print summary table, save timestamped JSON report            │
└──────────┬───────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────┐
│  metrics.py                                                      │
│                                                                  │
│  System metrics:  tokens, latency, cost, tool calls, errors      │
│  Quality metrics: recall, citation, semantic correctness,        │
│                   query hallucination, answer hallucination       │
│                                                                  │
│  Quality metrics delegate to llm_judge.py (async, parallel)      │
└──────────┬───────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────┐
│  llm_judge.py  --  LLM-as-a-Judge (Claude Opus 4.6)             │
│                                                                  │
│  Three independent judges, run in parallel:                      │
│  1. Query hallucination -- trajectory-based; checks every search │
│     query against the user question + previously retrieved text  │
│  2. Answer hallucination -- checks every factual claim in the    │
│     final answer against the full retrieved Wikipedia context    │
│  3. Semantic correctness -- checks if the generated answer       │
│     matches the ground-truth answer (supports multiple options)  │
│                                                                  │
│  Each returns { flag: bool, reasoning: str }                     │
└──────────────────────────────────────────────────────────────────┘
```

## Key Modules

### `agent/config.py`

Single source of truth for every tunable constant:

| Constant | Value | Purpose |
|---|---|---|
| `MODEL` | `claude-opus-4-6` | Anthropic model ID |
| `MAX_TOKENS` | `16000` | Max output tokens per LLM call |
| `TEMPERATURE` | `0` | Deterministic output |
| `MAX_TURNS` | `5` | Safety cap on agent loop iterations |
| `WIKI_API_URL` | `https://en.wikipedia.org/w/api.php` | MediaWiki endpoint |
| `WIKI_SEARCH_RESULTS_LIMIT` | `3` | Pages returned per search |
| `WIKI_MAX_EXTRACT_CHARS` | `6000` | Per-article extract truncation |
| `WIKI_REQUEST_TIMEOUT` | `15` | HTTP timeout for Wikipedia (seconds) |
| `MAX_RETRIES` | `3` | Retry attempts for API/HTTP errors |
| `RETRY_BASE_DELAY` | `1.0` | Initial backoff delay (seconds) |
| `RETRY_MAX_DELAY` | `30.0` | Backoff cap (seconds) |
| `EVAL_CONCURRENCY` | `3` | Max parallel agent runs in eval |

### `agent/prompts.py`

Contains `SYSTEM_PROMPT` -- the system-level instruction given to Claude on every call. Separated from logic so prompts can be reviewed and modified safely without touching the event loop.

The prompt uses **XML-structured sections** for clarity:

- **`<role>`** — defines the agent as a factual QA assistant that relies solely on retrieved Wikipedia content.
- **`<thinking_protocol>`** — step-by-step reasoning before every action:
  - Identify entities and relationships in the user's question.
  - Check for ambiguity (pre-search vagueness or post-search disambiguation when results reveal multiple distinct entities).
  - Classify the question as simple (single search) or complex/multi-hop (plan parallel or sequential searches).
  - Construct queries using only terms from the question or retrieved text.
  - Evaluate context after each search before deciding next steps.
- **`<rules>`** — strict guardrails:
  - *Query rules*: keyword-based queries only; no injecting external knowledge; multi-hop plans before execution.
  - *Answer rules*: every claim must be traceable to retrieved text; admit uncertainty rather than guess, even at max iterations.
  - *Scope rules*: decline predictions, opinions, and real-time events.
- **`<output_format>`** — cite Wikipedia article titles inline with `(Source: "Title")`.

### `agent/clients.py`

Centralized, lazily-initialized singletons:

- **`anthropic_client`** -- `anthropic.AsyncAnthropic()` instance. Reads `ANTHROPIC_API_KEY` from the `.env` file (loaded via `python-dotenv` at import time).
- **`wiki_get(params)`** -- async function wrapping a shared `aiohttp.ClientSession`. Automatically retries on `aiohttp.ClientError` and `asyncio.TimeoutError` with exponential backoff.
- **`close_wiki_session()`** -- cleanup function called in `finally` blocks by entry points.

### `agent/wikipedia_client.py`

Two-phase retrieval using the MediaWiki Action API directly (no third-party Wikipedia library):

1. **Search**: `action=query&list=search` to find the top N page titles matching the query.
2. **Fetch**: `action=query&prop=extracts&explaintext=1` to pull plain-text content for those pages, truncated to `WIKI_MAX_EXTRACT_CHARS`.

Each article is fetched individually and concurrently (`asyncio.gather`) to avoid the MediaWiki API silently dropping extracts when multiple large articles are batched in a single request. If a full extract returns empty (oversized article), the client falls back to fetching the intro section only.

Returns a formatted string with `=== Title ===` headers for each article.

### `agent/agent.py`

The async event loop:

1. Wraps LLM calls in `_call_llm()` which retries on rate-limit, server, connection, and timeout errors. Uses `temperature=0` for deterministic output.
2. Loops up to `MAX_TURNS` times, handling `tool_use` stop reasons by dispatching tools and feeding results back.
3. On `end_turn`, extracts the final text answer.
4. Tracks `task_completed` (whether the agent finished within `MAX_TURNS`) and `error_count` (API failures encountered, including retried ones).
5. Delegates all trace recording to `TraceLogger`.

### `agent/logger.py`

`TraceLogger` accumulates structured data for one query execution:

- Per-turn: request metadata, response content summary, tool executions (name, input, result preview, duration, error flag).
- Across turns: `error_count`, `task_completed`, `tool_queries` (list of all search query strings), `tool_results_full` (complete tool output for downstream eval).
- On finalize: computes `usage_summary` (total input/output tokens, tool call count, latency, LLM turns), writes a JSON trace file to `agent/logs/`.

### `agent/tools.py`

- `TOOLS`: list of tool definitions in Anthropic tool-use schema format. Currently one tool: `search_wikipedia`. The tool description specifies three usage patterns (single search, parallel searches, iterative sequential searches). The input schema requires keyword-based queries (not natural language sentences).
- `dispatch_tool(name, input)`: async routing function that maps tool names to implementations.

### `demo.py`

Interactive CLI with three modes for team demos:

- **Interactive REPL** (`python demo.py`): type questions, get answers in a loop.
- **Demo mode** (`python demo.py --demo`): runs 5 sample queries automatically (simple factual, multi-hop, out-of-scope).
- **Single query** (`python demo.py -q "..."`): answer one question and exit.

Output shows Wikipedia searches executed, the sourced answer, and a stats line (model, tokens, tool calls, latency).

## Eval Suite

### `eval/config.py`

Single source of truth for eval-specific constants:

| Constant | Value | Purpose |
|---|---|---|
| `TEST_CASES_PATH` | `eval/test_cases.json` | Path to the basic test case file |
| `GOLDEN_TEST_CASES_PATH` | `eval/golden_test_cases.json` | Path to the golden test set |
| `RESULTS_DIR` | `eval/results/` | Directory for eval report output |
| `INPUT_COST_PER_TOKEN` | `$5 / 1M tokens` | Claude Opus 4.6 input pricing |
| `OUTPUT_COST_PER_TOKEN` | `$25 / 1M tokens` | Claude Opus 4.6 output pricing |
| `JUDGE_MODEL` | `claude-opus-4-6` | Model used for LLM-as-a-Judge evaluations |
| `JUDGE_MAX_TOKENS` | `1024` | Max output tokens for judge calls |
| `JUDGE_TEMPERATURE` | `0` | Deterministic judge output |
| `JUDGE_CONCURRENCY` | `5` | Max parallel judge calls |

### `eval/test_cases.json`

JSON array of basic test cases, each with `id` and `question`. Seeded with 5 questions for quick smoke tests.

### `eval/golden_test_cases.json`

Comprehensive golden test set (30 questions) for error analysis and evaluation. Each entry includes `id`, `category`, `source`, `question`, and `expected_answer`. Categories:

| Category | Count | Source | Purpose |
|---|---|---|---|
| `simple_factual` | 10 | Natural Questions | Direct factual recall from a single Wikipedia article |
| `multi_hop` | 10 | HotpotQA | Reasoning across multiple articles to derive an answer |
| `out_of_scope` | 5 | Synthetic | Questions Wikipedia cannot answer (predictions, opinions) |
| `ambiguous` | 5 | Synthetic | Vague or underspecified questions lacking sufficient context |

### `eval/metrics.py`

Extracts both system metrics and quality metrics from agent traces:

**System metrics** (derived directly from the trace):
- Input / output / total tokens
- Tool call count and LLM turns
- Latency (wall-clock seconds)
- Estimated USD cost (using Claude Opus 4.6 pricing)
- Task completion flag (finished within `MAX_TURNS`)
- Error count (API failures encountered)

**Quality metrics** (require ground-truth or LLM judge):
- **Recall** — fraction of ground-truth answer tokens found in the generated answer (exact token overlap after normalization).
- **Citation** — rule-based substring check for `Source:` or `Sources:` in the final answer. Only evaluated for queries that invoked tools; non-tool queries return `None` to avoid penalization.
- **Semantic correctness** — LLM-as-a-Judge (via `llm_judge.py`): whether the generated answer is semantically equivalent to the ground truth. Supports multiple acceptable answers in the ground truth.
- **Query hallucination** — LLM-as-a-Judge: trajectory-based evaluation of every search query against the user's original question plus all previously retrieved context.
- **Answer hallucination** — LLM-as-a-Judge: whether every factual claim in the final answer is grounded in the full retrieved Wikipedia context.

The three LLM judge calls run concurrently via `asyncio.gather` for each query.

`aggregate_metrics()` computes totals and averages across a batch, including rates for task completion, semantic correctness, citation, and counts for hallucinations.

### `eval/llm_judge.py`

LLM-as-a-Judge framework using Claude Opus 4.6 as the evaluator. Three independent judges:

1. **Query hallucination judge** — evaluates the full multi-step search trajectory. The first query must derive entirely from the user's question. Subsequent queries may incorporate entities discovered in previously retrieved context, but must not introduce terms unsupported by either the original question or prior results. Returns `{ hallucinated: bool, reasoning: str }`.

2. **Answer hallucination judge** — receives the final answer and the complete retrieved Wikipedia context (no truncation). Checks every factual claim (names, dates, numbers, causal relationships) against the context. Returns `{ hallucinated: bool, reasoning: str }`.

3. **Semantic correctness judge** — compares the generated answer against the ground-truth answer. Returns correct (`Y`) as long as the core meaning is captured. When the ground truth contains multiple acceptable answers (separated by "/" or "or"), the generated answer is correct if it matches any one of them. Returns `{ correct: bool, reasoning: str }`.

All judge prompts use few-shot examples that are synthetic (not drawn from the golden test set) to prevent data leakage.

### `eval/eval_runner.py`

- Loads test cases from JSON (optionally filtered by `--cases q1,q3`).
- Supports `--golden` flag to use the golden test set instead of the basic one.
- Runs all cases concurrently via `asyncio.gather()`, bounded by an `asyncio.Semaphore(EVAL_CONCURRENCY)`.
- Each result includes: input data (question, expected answer, category), execution trace (turns, tool queries, tool results, final answer), and all evaluation metrics.
- Prints a formatted summary table (via `tabulate`) with columns: ID, Done, Errs, Tokens, Tools, Latency, Cost, Recall, Sem, Cite, Q-Hal, A-Hal.
- Saves a timestamped JSON report to `eval/results/`.

### `eval/EVAL_DESIGN.md`

Living document that tracks the evaluation design and performance history across versions. Each version records configuration changes, a full results table for all 30 golden questions, aggregate statistics, and observations. See that file for detailed version-by-version performance data (v0 through v4).

## Retry & Resilience

Both the Anthropic API and Wikipedia HTTP calls use the same retry strategy:

```
for attempt in 1..MAX_RETRIES:
    try call
    on transient error:
        if last attempt: raise
        delay = min(RETRY_BASE_DELAY * 2^(attempt-1), RETRY_MAX_DELAY)
        sleep(delay)
```

**Anthropic retried errors**: `RateLimitError`, `InternalServerError`, `APIConnectionError`, `APITimeoutError`.

**Wikipedia retried errors**: `aiohttp.ClientError`, `asyncio.TimeoutError`.

## Usage

```bash
# Set your API key
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# Install dependencies
pip install anthropic aiohttp python-dotenv tabulate

# Interactive demo (REPL)
python demo.py

# Auto-run sample queries
python demo.py --demo

# Ask a single question
python demo.py -q "What is the tallest building in the world?"

# Run basic eval suite (5 smoke-test questions)
python -m eval.eval_runner

# Run full golden test set (30 questions)
python -m eval.eval_runner --golden

# Run specific test cases
python -m eval.eval_runner --cases q1,q3
```

## Limitations & Future Work

### Single-turn only (no conversation memory)

Each call to `run_agent(query)` initializes a fresh message list. There is no shared state between questions, so the agent cannot handle follow-up references like "what else did she write?" after a previous answer. The interactive REPL in `demo.py` lets the user ask many questions sequentially, but each is answered in complete isolation.

**Next step**: maintain a rolling conversation buffer and pass prior turns into each `messages` list, enabling contextual follow-ups within a session.

### Wikipedia-only knowledge source

The agent can only answer questions that have a Wikipedia article. Questions about very recent events (post Wikipedia's last edit), niche topics with no article, or highly localized information will fail silently or return a "unable to find" response. The system has no fallback to other knowledge sources.

**Next step**: add additional retrieval tools (e.g. news APIs, domain-specific databases) and let the agent choose the right source based on question type.

### English Wikipedia only

The client is hardcoded to `en.wikipedia.org`. Questions best answered by non-English Wikipedia editions (e.g. regional history, local figures) may return incomplete or no results.

**Next step**: detect question language or topic region and route to the appropriate Wikipedia edition.

### Extract truncation may lose answer-bearing text

Each article is truncated to `WIKI_MAX_EXTRACT_CHARS` (6,000 characters) before being passed to the LLM. For long articles, the answer may appear in a section that gets cut off, causing the agent to either search again or admit it cannot find the information.

**Next step**: implement section-aware retrieval — identify which section headings are relevant and fetch only those sections, rather than truncating the full article top-down.

### No real-time or dynamic content

Wikipedia is a static snapshot. The agent cannot answer questions that depend on live data such as current prices, scores, weather, or breaking news. Attempts to do so are correctly declined, but no real-time fallback is offered.

**Next step**: integrate a real-time data tool (e.g. a search API or structured data feed) for time-sensitive queries.

### Eval cost (LLM-as-a-Judge)

Running the full 30-question golden test set triggers three LLM judge calls per query (query hallucination, answer hallucination, semantic correctness), tripling the API cost of each eval run relative to agent-only cost. Judge costs are currently not separated from agent costs in the metrics output.

**Next step**: track and report judge token usage and cost separately; explore caching judge verdicts for re-runs where only the agent changed.

---

## Dependencies

| Package | Purpose |
|---|---|
| `anthropic` | Async client for the Anthropic Messages API |
| `aiohttp` | Async HTTP for Wikipedia MediaWiki API |
| `python-dotenv` | Load `ANTHROPIC_API_KEY` from `.env` |
| `tabulate` | Format eval summary tables |
