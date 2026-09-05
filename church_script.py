import json
import logging
import re

from google import genai
from google.genai import types

from config import config
from retry_utils import retry_with_backoff
import topic_history
import performance_guidance

logger = logging.getLogger("video_pipeline")

# Cliffhanger phrase is dynamically numbered per segment ("Follow for part 2",
# "Follow for part 3", etc.) - NOT the same hardcoded phrase for every segment,
# which would be nonsensical once there are more than 2 segments.
def _follow_phrase(next_segment_number: int) -> str:
    return f"Follow for part {next_segment_number}"

# Must match the enums the stick-figure render library actually supports -
# the model is constrained to pick from these, not free-form image descriptions.
VALID_POSES = ["walking", "standing", "sitting", "kneeling", "praying", "teaching", "pointing"]
VALID_ROBE_COLORS = ["white", "red", "blue", "brown", "purple", "green"]
VALID_SKIES = ["desert", "temple", "sea", "night", "plain"]
VALID_LANDMARKS = ["temple", "hills", "ship", "wall", None]
VALID_PROPS = ["staff", "scroll", "cross", None]

# Calibrated against REAL measured TTS output for this pipeline's en-US voice pool
# at 1.5x (148 words -> 29.6s measured in production, i.e. ~5.0 words/sec) - NOT a
# rough estimate. Segments need to genuinely fill 1-1.5 minutes (60-90s) as originally
# specified, which requires roughly 300-450 words, not the much lower number an
# unverified guess originally used.
MIN_SEGMENT_WORDS = 300
MAX_SEGMENT_WORDS = 450
TARGET_SEGMENT_COUNT_MIN = 7
TARGET_SEGMENT_COUNT_MAX = 9
# A 60-90 second segment shown as a single unchanging still image is visually flat -
# require real scene variety within each segment.
MIN_SCENES_PER_SEGMENT = 3
MAX_SCENES_PER_SEGMENT = 5

# Some robe/sky color pairings render as nearly the same shade, making the figure
# blend into the background instead of standing out - reject these combinations.
LOW_CONTRAST_PAIRS = {("white", "temple"), ("white", "plain"), ("green", "night")}

SYSTEM_PROMPT = f"""You are a historian and scriptwriter creating short-form narration videos \
about real, documented church history - early Christianity, church fathers, missionary \
movements, councils and controversies, persecutions, reformations, and notable religious \
figures across all eras and regions. You have access to Google Search - use it to verify \
facts and ground your account in real historical sources, not invented details.

You are telling ONE complete, true historical story in full. The story is broken into \
{TARGET_SEGMENT_COUNT_MIN}-{TARGET_SEGMENT_COUNT_MAX} short segments (each a 1-1.5 minute \
chapter, {MIN_SEGMENT_WORDS}-{MAX_SEGMENT_WORDS} words), which post first as a series, \
building up the full story with a "Follow for part N"-style hook (dynamically numbered - segment 1 says
"Follow for part 2", segment 2 says "Follow for part 3", and so on) at the end of every segment except the last. Days later, all segments are combined into one full-length video.

For the VISUAL side: each segment must be broken into {MIN_SCENES_PER_SEGMENT}-{MAX_SCENES_PER_SEGMENT} \
distinct scenes - a single unchanging image for a full 60-90 second segment is visually flat, so \
real scene variety within each segment is required, not optional. Since figures are simple \
stick-figure illustrations (not photorealistic), each scene must specify its visuals using ONLY \
these exact values - do not invent new ones:
- pose: one of {VALID_POSES}
- robe_color: one of {VALID_ROBE_COLORS}
- sky: one of {VALID_SKIES}
- landmark: one of {['"' + l + '"' for l in VALID_LANDMARKS if l]} or null
- prop: one of {['"' + p + '"' for p in VALID_PROPS if p]} or null

IMPORTANT: never pair robe_color="white" with sky="temple" or sky="plain", and never pair \
robe_color="green" with sky="night" - these specific combinations render as nearly the same \
shade and make the figure disappear into the background. Every other combination is fine.

Output ONLY valid JSON, no markdown fences, no commentary, matching this schema exactly:
{{
  "topic": string,                  // the specific historical event/story you selected, 1 sentence
  "sources_note": string,           // brief note on what grounded this (for internal QA, not shown to viewers)
  "segments": [
    {{
      "segment_number": number,
      "title": string,
      "social_title": string,
      "caption": string,
      "scenes": [
        {{
          "narration": string,
          "pose": string, "robe_color": string, "sky": string, "landmark": string | null, "prop": string | null
        }}
      ]
    }}
  ],
  "full_compilation": {{
    "title": string,
    "social_title": string,
    "caption": string
  }}
}}
"segments" must contain {TARGET_SEGMENT_COUNT_MIN}-{TARGET_SEGMENT_COUNT_MAX} objects. Every segment except the last must end its final scene's narration with the exact phrase
"Follow for part N" where N is that segment's own number plus one (segment 1 -> "Follow for part 2",
segment 2 -> "Follow for part 3", etc.), and its caption must include that same phrase too. The last segment resolves the \
story with no follow phrase. "full_compilation" reuses the same title style for the eventual \
combined long-form video - do not write its own scenes; the full narration is just all segments' \
narration concatenated in order.
"""


def _append_performance_guidance(prompt: str) -> str:
    guidance = performance_guidance.load_guidance()
    if not guidance:
        return prompt
    return prompt + f"\n\nADDITIONAL GUIDANCE FROM RECENT PERFORMANCE DATA: {guidance}"


def build_user_prompt() -> str:
    covered = topic_history.get_covered_topic_titles()
    covered_block = (
        "\n".join(f"- {t}" for t in covered) if covered else "(none yet - this is the first story)"
    )
    return f"""Select ONE specific, real, well-documented church history event or story to tell \
in full, then write the complete script for it.

Do NOT repeat or closely overlap with any of these already-covered topics:
{covered_block}

Use Google Search to verify the historical details you include are accurate. Prefer a specific, \
well-documented event over a vague generalization (e.g. "Patrick's escape from slavery in \
Ireland" rather than "the history of Irish Christianity").

Return ONLY the JSON object described in your instructions, nothing else."""


def _strip_code_fences(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    return raw


@retry_with_backoff(max_retries=config.max_retries, base_delay=config.retry_base_delay)
def _call_gemini_grounded() -> str:
    """
    Uses Gemini's Google Search grounding tool so the model's account is checked
    against real, current web sources rather than relying only on training data.
    """
    client = genai.Client(api_key=config.gemini_api_key)
    response = client.models.generate_content(
        model=config.gemini_text_model,
        contents=_append_performance_guidance(build_user_prompt()),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        ),
    )
    return response.text


def _validate_scene(scene: dict):
    if scene["pose"] not in VALID_POSES:
        raise ValueError(f"Invalid pose: {scene['pose']!r}")
    if scene["robe_color"] not in VALID_ROBE_COLORS:
        raise ValueError(f"Invalid robe_color: {scene['robe_color']!r}")
    if scene["sky"] not in VALID_SKIES:
        raise ValueError(f"Invalid sky: {scene['sky']!r}")
    if scene.get("landmark") not in VALID_LANDMARKS:
        raise ValueError(f"Invalid landmark: {scene.get('landmark')!r}")
    if scene.get("prop") not in VALID_PROPS:
        raise ValueError(f"Invalid prop: {scene.get('prop')!r}")
    if (scene["robe_color"], scene["sky"]) in LOW_CONTRAST_PAIRS:
        raise ValueError(
            f"robe_color={scene['robe_color']!r} on sky={scene['sky']!r} renders as nearly "
            f"the same shade (low contrast) - choose a different robe color or sky for this scene"
        )


def _validate_and_parse(raw: str) -> dict:
    data = json.loads(_strip_code_fences(raw))

    segments = data["segments"]
    if not (TARGET_SEGMENT_COUNT_MIN <= len(segments) <= TARGET_SEGMENT_COUNT_MAX):
        raise ValueError(f"Expected {TARGET_SEGMENT_COUNT_MIN}-{TARGET_SEGMENT_COUNT_MAX} segments, got {len(segments)}")

    for i, seg in enumerate(segments):
        word_count = sum(len(sc["narration"].split()) for sc in seg["scenes"])
        if word_count < MIN_SEGMENT_WORDS:
            raise ValueError(f"Segment {i+1} has {word_count} words, under the {MIN_SEGMENT_WORDS} minimum")
        if not (MIN_SCENES_PER_SEGMENT <= len(seg["scenes"]) <= MAX_SCENES_PER_SEGMENT):
            raise ValueError(
                f"Segment {i+1} has {len(seg['scenes'])} scene(s), expected "
                f"{MIN_SCENES_PER_SEGMENT}-{MAX_SCENES_PER_SEGMENT} for visual variety within a 60-90s segment"
            )
        for scene in seg["scenes"]:
            _validate_scene(scene)

    last_narration = segments[-1]["scenes"][-1]["narration"]
    if "follow for part" in last_narration.lower():
        raise ValueError("Last segment should NOT contain a follow-phrase, but it does")

    for i, seg in enumerate(segments[:-1]):
        expected_phrase = _follow_phrase(i + 2)  # segment i+1 (1-indexed) points to part i+2
        last_scene_narration = seg["scenes"][-1]["narration"]
        caption = seg["caption"]
        if expected_phrase.lower() not in last_scene_narration.lower():
            raise ValueError(f"Segment {i+1} is missing the exact phrase {expected_phrase!r} in its narration")
        if expected_phrase.lower() not in caption.lower():
            raise ValueError(f"Segment {i+1} is missing the exact phrase {expected_phrase!r} in its caption")

    if "topic" not in data or not data["topic"].strip():
        raise ValueError("Missing 'topic' field")
    if "full_compilation" not in data:
        raise ValueError("Missing 'full_compilation' field")

    return data


def generate_church_history_story() -> dict:
    """
    Generates one complete, search-grounded church history story: N short segments
    plus full-compilation metadata. Raises on failure (caller handles fallback to
    local pool) rather than silently returning something structurally invalid.
    """
    logger.info("Generating search-grounded church history story via Gemini")
    raw = _call_gemini_grounded()
    data = _validate_and_parse(raw)
    logger.info(
        f"Story ready: topic={data['topic']!r}, {len(data['segments'])} segments, "
        f"word counts: {[sum(len(sc['narration'].split()) for sc in s['scenes']) for s in data['segments']]}"
    )
    return data
