"""Centralized configuration for the eval suite.

All tunable constants for evaluation live here.
"""

from pathlib import Path

# --- Paths ---
TEST_CASES_PATH = Path(__file__).parent / "test_cases.json"
GOLDEN_TEST_CASES_PATH = Path(__file__).parent / "golden_test_cases.json"
RESULTS_DIR = Path(__file__).parent / "results"

# --- Cost model (Claude Opus 4.6 pricing, USD per token) ---
INPUT_COST_PER_TOKEN = 5.0 / 1_000_000    # $5 per 1M input tokens
OUTPUT_COST_PER_TOKEN = 25.0 / 1_000_000   # $25 per 1M output tokens

# --- LLM-as-a-Judge ---
JUDGE_MODEL = "claude-opus-4-6"
JUDGE_MAX_TOKENS = 1024
JUDGE_TEMPERATURE = 0
JUDGE_CONCURRENCY = 5
