"""Centralized async client initialization with retry support.

Other modules import the ready-to-use singletons from here instead of
constructing their own instances.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

import aiohttp
import anthropic

from agent.config import (
    MAX_RETRIES,
    RETRY_BASE_DELAY,
    RETRY_MAX_DELAY,
    WIKI_API_URL,
    WIKI_REQUEST_TIMEOUT,
)

logger = logging.getLogger(__name__)


def _load_env() -> None:
    """Load .env from the project root (parent of the agent/ package)."""
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(__file__), os.pardir, ".env")
    load_dotenv(os.path.abspath(env_path))


_load_env()

# --- Anthropic async client (reads ANTHROPIC_API_KEY from env) ---
anthropic_client = anthropic.AsyncAnthropic()

# --- Shared aiohttp session (created lazily, one per event loop) ---
_wiki_session: Optional[aiohttp.ClientSession] = None


async def _get_wiki_session() -> aiohttp.ClientSession:
    global _wiki_session
    if _wiki_session is None or _wiki_session.closed:
        _wiki_session = aiohttp.ClientSession(
            headers={"User-Agent": "WikiQABot/1.0 (educational project)"},
            timeout=aiohttp.ClientTimeout(total=WIKI_REQUEST_TIMEOUT),
        )
    return _wiki_session


async def close_wiki_session() -> None:
    """Cleanly close the shared aiohttp session."""
    global _wiki_session
    if _wiki_session and not _wiki_session.closed:
        await _wiki_session.close()
        _wiki_session = None


async def wiki_get(params: dict) -> dict[str, Any]:
    """GET the MediaWiki API with automatic retries on transient failures."""
    session = await _get_wiki_session()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with session.get(WIKI_API_URL, params=params) as resp:
                resp.raise_for_status()
                return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if attempt == MAX_RETRIES:
                logger.error("Wiki API failed after %d attempts: %s", MAX_RETRIES, e)
                raise
            delay = min(RETRY_BASE_DELAY * (2 ** (attempt - 1)), RETRY_MAX_DELAY)
            logger.warning(
                "Wiki API attempt %d/%d failed (%s), retrying in %.1fs",
                attempt, MAX_RETRIES, e, delay,
            )
            await asyncio.sleep(delay)

    raise RuntimeError("Unreachable")  # satisfies type checker
