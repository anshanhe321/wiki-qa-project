# Wiki QA — Wikipedia Question Answering System

A question-answering system that retrieves information from Wikipedia and generates accurate, sourced answers using Claude. Includes a comprehensive evaluation suite with LLM-as-a-Judge metrics for hallucination detection, semantic correctness, and citation verification.

## Quick Start

### 1. Prerequisites

- **Python 3.9+**
- **Anthropic API key** ([get one here](https://console.anthropic.com/))

### 2. Install dependencies

```bash
pip install anthropic aiohttp python-dotenv tabulate
```

### 3. Set your API key

Create a `.env` file in the project root:

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
```

### 4. Run the demo

```bash
# Interactive mode — type questions, get answers
python demo.py

# Demo mode — runs 5 sample queries automatically
python demo.py --demo

# Single question
python demo.py -q "Who invented the telephone?"
```

## How It Works

```
User Question
     │
     ▼
┌─────────────┐     ┌──────────────────┐     ┌────────────────┐
│  Claude LLM │────▶│ search_wikipedia │────▶│ MediaWiki API  │
│  (Opus 4.6) │◀────│   tool call      │◀────│  (en.wiki)     │
└─────────────┘     └──────────────────┘     └────────────────┘
     │
     ▼
Sourced Answer
```

1. The user asks a question.
2. Claude analyzes the question, plans a search strategy, and calls `search_wikipedia` with keyword queries.
3. The tool hits the MediaWiki API to find relevant articles and returns plain-text extracts.
4. Claude reads the retrieved context and produces a final answer citing Wikipedia sources.
5. For complex multi-hop questions, steps 2–4 repeat (up to 5 iterations) with refined queries.

## Project Structure

```
wiki_qa_project/
├── demo.py                        # Interactive demo CLI (start here)
├── .env                           # Your Anthropic API key
│
├── agent/                         # The QA agent
│   ├── config.py                  # Model, tokens, retry settings
│   ├── prompts.py                 # System prompt (XML-structured)
│   ├── clients.py                 # Async Anthropic + Wikipedia clients
│   ├── wikipedia_client.py        # Two-phase MediaWiki retrieval
│   ├── tools.py                   # Tool schema + dispatch
│   ├── agent.py                   # Core async event loop with retry
│   ├── logger.py                  # Structured JSON trace logging
│   ├── main.py                    # CLI entry point (single query)
│   └── logs/                      # Auto-generated trace files
│
├── eval/                          # Evaluation suite
│   ├── config.py                  # Eval-specific settings
│   ├── metrics.py                 # Metric extraction + aggregation
│   ├── llm_judge.py               # LLM-as-a-Judge (hallucination, correctness)
│   ├── eval_runner.py             # Concurrent eval runner
│   ├── test_cases.json            # Smoke test cases (5 questions)
│   ├── golden_test_cases.json     # Full test set (30 questions)
│   ├── EVAL_DESIGN.md             # Eval design + version history
│   └── results/                   # Auto-generated eval reports
│
└── DESIGN.md                      # System design & architecture
```

## Running the Evaluation Suite

```bash
# Run the 5 smoke-test questions
python -m eval.eval_runner

# Run the full 30-question golden test set
python -m eval.eval_runner --golden

# Run specific cases
python -m eval.eval_runner --golden --cases nq_01,hp_03,oos_02
```

The eval suite measures:

| Metric | Description |
|--------|-------------|
| Task completion | Did the agent finish within max iterations? |
| Token usage / cost | Input + output tokens and estimated USD cost |
| Latency | End-to-end wall-clock time per query |
| Recall | Key-term overlap with ground-truth answer |
| Semantic correctness | LLM judge: does the answer match ground truth? |
| Citation | Does the answer cite Wikipedia sources? |
| Query hallucination | LLM judge: are search queries grounded in the question + retrieved context? |
| Answer hallucination | LLM judge: is the answer supported by retrieved context? |

See [`eval/EVAL_DESIGN.md`](eval/EVAL_DESIGN.md) for the full evaluation design and performance history across versions.

## Sample Output

```
  Question: Who wrote the novel '1984'?

  🔍 Wikipedia searches (1):
     1. "1984 novel author"

──────────────────────────────────────────────────────────────
  ANSWER:
──────────────────────────────────────────────────────────────
  The novel *Nineteen Eighty-Four* (commonly referred to as
  *1984*) was written by English author George Orwell. It was
  published on 8 June 1949 by Secker & Warburg.
  (Source: "Nineteen Eighty-Four")
──────────────────────────────────────────────────────────────
  Model: claude-opus-4-6  |  Tokens: 8,234  |  Tools: 1  |  Latency: 6.2s
```

## Configuration

Key settings in `agent/config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `MODEL` | `claude-opus-4-6` | Anthropic model to use |
| `MAX_TURNS` | `5` | Max LLM iterations per question |
| `MAX_TOKENS` | `16000` | Max output tokens per LLM call |
| `TEMPERATURE` | `0` | Deterministic output |
| `WIKI_SEARCH_RESULTS_LIMIT` | `3` | Articles returned per search |
| `MAX_RETRIES` | `3` | Retry count for API failures |
