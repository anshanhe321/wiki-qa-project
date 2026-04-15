"""Centralized configuration for the Wiki QA agent.

All tunable constants live here so they can be adjusted in one place.
"""

from pathlib import Path

# --- Anthropic LLM ---
MODEL = "claude-opus-4-6"
MAX_TOKENS = 16000
TEMPERATURE = 0
MAX_TURNS = 5

# --- Wikipedia retrieval ---
WIKI_API_URL = "https://en.wikipedia.org/w/api.php"
WIKI_SEARCH_RESULTS_LIMIT = 3
WIKI_MAX_EXTRACT_CHARS = 6000
WIKI_REQUEST_TIMEOUT = 15  # seconds

# --- Retry / resilience ---
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0    # seconds; doubles each attempt (exponential backoff)
RETRY_MAX_DELAY = 30.0    # cap on backoff delay

# --- Concurrency ---
EVAL_CONCURRENCY = 3  # max simultaneous agent runs during eval

# --- Logging ---
LOGS_DIR = Path(__file__).parent / "logs"
LOG_TEXT_PREVIEW_CHARS = 500
LOG_TOOL_RESULT_PREVIEW_CHARS = 1000
