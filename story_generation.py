import json
import logging
import random
from pathlib import Path

from config import config
import church_script
import mistral_script
import topic_history

logger = logging.getLogger("video_pipeline")

SCRIPTS_DIR = Path(__file__).resolve().parent / "scripts"
SERIES_DIR = SCRIPTS_DIR / "series"


def _load_random_local_series(exclude_files: set[str] = None) -> tuple[dict, str]:
    """
    Picks a local fallback story, preferring one whose topic has never been covered
    before (checked against the SAME topic_history the AI-generation path uses) -
    not just avoiding a same-day collision with a sibling track. With only a handful
    of local stories, every one will eventually get told more than once over a long
    enough time, but this ordering means that only happens after the full pool has
    actually been exhausted, not on the very next time the fallback tier triggers.
    """
    candidates = sorted(SERIES_DIR.glob("*.json"))
    if not candidates:
        raise RuntimeError(f"No series files found in {SERIES_DIR} and Gemini story generation is unavailable")
    exclude_files = exclude_files or set()

    loaded = []
    for c in candidates:
        if c.name in exclude_files:
            continue
        with open(c) as f:
            loaded.append((c, json.load(f)))

    covered_topics = set(topic_history.get_covered_topic_titles())
    never_told = [(c, d) for c, d in loaded if d["topic"] not in covered_topics]

    if never_told:
        chosen, data = random.choice(never_told)
        logger.info(f"Using hand-written story at {chosen} (never told before - {len(never_told)} of {len(candidates)} still fresh)")
        return data, chosen.name

    if loaded:
        logger.warning(
            f"All {len(loaded)} available local stories have already been told at least once - "
            f"the full pool is exhausted, allowing a repeat rather than failing."
        )
        chosen, data = random.choice(loaded)
        return data, chosen.name

    logger.warning(f"All {len(candidates)} local stories are in use by other tracks today - allowing a same-day repeat rather than failing.")
    chosen = random.choice(candidates)
    with open(chosen) as f:
        data = json.load(f)
    return data, chosen.name


def generate_story_with_fallback(exclude_local_files: set[str] = None) -> tuple[dict, str | None]:
    """
    Three tiers: Gemini with native Search Grounding -> Mistral+Tavily manual
    grounding (Mistral proposes a topic, Tavily searches real sources, Mistral
    writes the story constrained to those sources) -> local fallback pool. Unlike
    other pipelines, there's no ungrounded fallback tier (no plain Groq call) - an
    AI generating historical claims with no way to verify them defeats the whole
    point of this pipeline, so every AI tier here does real fact-checking one way
    or another. Returns (story_data, source_file) - source_file is the local pool
    filename if that tier was used, else None.
    """
    if config.gemini_api_key:
        try:
            story_data = church_script.generate_church_history_story()
            return story_data, None
        except Exception as e:
            logger.warning(f"Gemini search-grounded story generation failed after retries: {e}")

    if config.mistral_api_key and config.tavily_api_key:
        try:
            story_data = mistral_script.generate_mistral_grounded_story()
            return story_data, None
        except Exception as e:
            logger.warning(f"Mistral+Tavily grounded story generation failed after retries: {e}")

    logger.info("Falling back to local story pool")
    return _load_random_local_series(exclude_local_files)
