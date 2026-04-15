"""Wikipedia retrieval client using the MediaWiki Action API (async)."""

import asyncio

from agent.clients import wiki_get
from agent.config import WIKI_MAX_EXTRACT_CHARS, WIKI_SEARCH_RESULTS_LIMIT


async def search_wikipedia(query: str) -> str:
    """Search Wikipedia for a query and return plain-text extracts of top results.

    Two-phase approach:
      1. Search for page titles matching the query.
      2. Fetch plain-text extracts for those pages (one request per article
         to avoid the MediaWiki API silently dropping large extracts in
         batched requests).

    Returns a formatted string with article titles and their content.
    """
    titles = await _search_titles(query)
    if not titles:
        return f"No Wikipedia articles found for query: {query}"

    extracts = await _fetch_extracts(titles)
    if not extracts:
        return f"Found articles but could not retrieve content for query: {query}"

    sections = []
    for title, text in extracts.items():
        truncated = text[:WIKI_MAX_EXTRACT_CHARS]
        if len(text) > WIKI_MAX_EXTRACT_CHARS:
            truncated += "\n[...truncated]"
        sections.append(f"=== {title} ===\n{truncated}")

    return "\n\n".join(sections)


async def _search_titles(query: str, limit: int = WIKI_SEARCH_RESULTS_LIMIT) -> list[str]:
    """Phase 1: use action=query&list=search to find relevant page titles."""
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": limit,
        "format": "json",
    }
    data = await wiki_get(params)
    return [item["title"] for item in data.get("query", {}).get("search", [])]


async def _fetch_single_extract(title: str) -> tuple[str, str]:
    """Fetch the extract for a single article title.

    Tries a full extract first. If the API returns an empty extract (which
    happens for very long articles), falls back to the intro section only.
    """
    params = {
        "action": "query",
        "titles": title,
        "prop": "extracts",
        "explaintext": "1",
        "format": "json",
    }
    data = await wiki_get(params)
    text = _extract_text_from_response(data)

    if text:
        return title, text

    # Fallback: fetch intro section only for articles too large for full extract
    params["exintro"] = "1"
    data = await wiki_get(params)
    text = _extract_text_from_response(data)

    if text:
        return title, f"{text}\n[Note: intro section only; full article too large]"

    return title, ""


def _extract_text_from_response(data: dict) -> str:
    """Pull the extract string out of a MediaWiki query response."""
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        return page.get("extract", "")
    return ""


async def _fetch_extracts(titles: list[str]) -> dict[str, str]:
    """Phase 2: fetch plain-text extracts for each title individually and concurrently."""
    results = await asyncio.gather(*[_fetch_single_extract(t) for t in titles])
    return {title: text for title, text in results if text}
