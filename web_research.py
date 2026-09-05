import logging

import requests

from config import config
from retry_utils import retry_with_backoff

logger = logging.getLogger("video_pipeline")

TAVILY_URL = "https://api.tavily.com/search"


@retry_with_backoff(max_retries=2, base_delay=2.0)
def search_facts(query: str, max_results: int = 4) -> str:
    """
    Searches Tavily for real, current web content about `query` and returns it as a
    single block of plain text - each result's title, source URL, and extracted
    content - suitable for embedding directly into a prompt as grounding material.
    Raises if the search fails or returns nothing usable (caller should treat this
    as a hard failure, not silently write an ungrounded story).
    """
    if not config.tavily_api_key:
        raise RuntimeError("TAVILY_API_KEY not configured")

    resp = requests.post(
        TAVILY_URL,
        json={
            "api_key": config.tavily_api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
            "include_answer": False,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Tavily API error {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    results = data.get("results", [])
    if not results:
        raise RuntimeError(f"Tavily returned no results for query: {query!r}")

    blocks = []
    for r in results:
        title = r.get("title", "Untitled")
        url = r.get("url", "")
        content = (r.get("content") or "").strip()
        if not content:
            continue
        blocks.append(f"SOURCE: {title} ({url})\n{content}")

    if not blocks:
        raise RuntimeError(f"Tavily results for {query!r} had no usable content")

    logger.info(f"Tavily search for {query!r} returned {len(blocks)} usable source(s)")
    return "\n\n".join(blocks)
