import json
import logging
import re

import requests

from config import config
from retry_utils import retry_with_backoff
import topic_history
import web_research
import church_script  # reuses the SAME validation logic, schema constants, and follow-phrase helper

logger = logging.getLogger("video_pipeline")

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"


def _strip_code_fences(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    return raw


@retry_with_backoff(max_retries=2, base_delay=2.0)
def _call_mistral(system_prompt: str, user_prompt: str) -> str:
    if not config.mistral_api_key:
        raise RuntimeError("MISTRAL_API_KEY not configured")
    resp = requests.post(
        MISTRAL_URL,
        headers={"Authorization": f"Bearer {config.mistral_api_key}", "Content-Type": "application/json"},
        json={
            "model": config.mistral_text_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.7,
        },
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Mistral API error {resp.status_code}: {resp.text[:300]}")
    return resp.json()["choices"][0]["message"]["content"]


TOPIC_PROPOSAL_PROMPT = """You propose ONE specific, real Catholic Church history topic for a \
short-form documentary video, favoring the ancient/early church era (1st-5th century) most of \
the time, though later eras up to the present day are acceptable occasionally - including major \
historical splits (the Great Schism, the Reformation, origins of other Christian traditions).

Do NOT repeat or closely overlap with any of these already-covered topics:
{covered_block}

Respond with ONLY a JSON object: {{"topic": "one specific sentence naming the event/story", "search_query": "a short web search query (3-6 words) to research this topic"}}
"""


def _propose_topic() -> tuple[str, str]:
    covered = topic_history.get_covered_topic_titles()
    covered_block = "\n".join(f"- {t}" for t in covered) if covered else "(none yet)"
    raw = _call_mistral(
        "You are a historian proposing documentary topics.",
        TOPIC_PROPOSAL_PROMPT.format(covered_block=covered_block),
    )
    data = json.loads(_strip_code_fences(raw))
    return data["topic"], data["search_query"]


def _build_grounded_system_prompt(research_material: str) -> str:
    """
    Reuses church_script's exact schema/constraints instructions (same VALID_POSES,
    word counts, figures/crowd schema, subject constraints) so output from this path
    validates against the identical logic Gemini's output does - but replaces the
    "use Google Search" instruction with the ACTUAL search content already gathered,
    since Mistral has no search tool of its own to call.
    """
    base = church_script.SYSTEM_PROMPT.replace(
        "You have access to Google Search - use it to verify facts and ground your account in real historical sources, not invented details.",
        "You do NOT have web access. Base your account STRICTLY on the real source "
        "material provided below - do not add specific facts, dates, quotes, or "
        "details beyond what these sources actually support. If the sources don't "
        "cover something, keep that part general rather than inventing specifics.",
    )
    return base + f"\n\nREAL SOURCE MATERIAL TO BASE THIS STORY ON:\n{research_material}\n"


def generate_mistral_grounded_story() -> dict:
    """
    Manual grounding pipeline for when Gemini's native Search Grounding is
    unavailable: Mistral proposes a topic -> Tavily searches real sources for that
    topic -> Mistral writes the story constrained to those real sources. Raises on
    any failure (caller falls back to local pool), same as the Gemini path.
    """
    logger.info("Generating story via Mistral + Tavily (manual grounding)")
    topic, search_query = _propose_topic()
    logger.info(f"Mistral proposed topic: {topic!r} (search query: {search_query!r})")

    research_material = web_research.search_facts(search_query)

    system_prompt = _build_grounded_system_prompt(research_material)
    user_prompt = church_script.build_user_prompt().replace(
        "Select ONE specific, real, well-documented Catholic Church history event or story to tell in full, then write the complete script for it.",
        f'Write the complete script for this specific topic, already selected: "{topic}"',
    )

    raw = _call_mistral(system_prompt, user_prompt)
    data = church_script._validate_and_parse(raw)
    logger.info(
        f"Mistral-grounded story ready: topic={data['topic']!r}, {len(data['segments'])} segments"
    )
    return data
