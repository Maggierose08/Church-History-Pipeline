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
VALID_POSES = ["walking", "standing", "sitting", "kneeling", "praying", "teaching", "pointing", "writing", "raising_arms", "grieving"]
VALID_ROBE_COLORS = ["white", "red", "blue", "brown", "purple", "green"]
VALID_SKIES = ["desert", "temple", "sea", "night", "plain"]
VALID_LANDMARKS = ["temple", "hills", "ship", "wall", "prison", "arena", "road", "courtroom", None]
VALID_PROPS = ["staff", "scroll", "cross", "book", "torch", None]

# Speed changed to 1.2x with a switch to a British male Studio-tier voice, per
# explicit request. Word targets (240-360, up from the 200-300 used at 1.0x) are
# PROPORTIONALLY ESTIMATED from the previously measured real rate (5.0 words/sec
# at 1.5x, on a different voice/tier/accent) - not re-measured against this
# specific new voice. Verify the actual duration in the first real production
# log (look for "Final audio duration") and adjust these two constants if the
# real rate differs meaningfully from the ~4.0 words/sec this assumes.
MIN_SEGMENT_WORDS = 240
MAX_SEGMENT_WORDS = 360
TARGET_SEGMENT_COUNT_MIN = 10
TARGET_SEGMENT_COUNT_MAX = 14
# A 1-1.5 minute segment shown as a single unchanging still image is visually flat -
# require real scene variety within each segment.
MIN_SCENES_PER_SEGMENT = 3
MAX_SCENES_PER_SEGMENT = 5

# Some robe/sky color pairings render as nearly the same shade, making the figure
# blend into the background instead of standing out - reject these combinations.
LOW_CONTRAST_PAIRS = {("white", "temple"), ("white", "plain"), ("green", "night")}

# Each scene now shows 1-3 fully-detailed, interacting figures (not just one person
# standing alone), plus an optional simplified background crowd for moments that
# describe a genuine group (a mob, a gathering of bishops, a watching crowd).
MIN_FIGURES_PER_SCENE = 1
MAX_FIGURES_PER_SCENE = 3
MAX_CROWD_COUNT = 15

NARRATIVE_SYSTEM_PROMPT = f"""You are a historian and scriptwriter creating short-form narration videos \
about real, documented Catholic Church history, spanning from the time of Christ and the \
apostles up through the present day. Your PRIMARY focus should be the ancient and early \
church era (roughly the 1st through 5th centuries) - martyrs, apostles, church fathers, \
early councils, and the earliest missionary movements - since this is the era you should \
draw from most often. Stories from later centuries, including the medieval, Counter-\
Reformation, and modern eras, are acceptable but should be featured less frequently than \
the ancient era. You have access to Google Search - use it to verify facts and ground your \
account in real historical sources, not invented details.

IMPORTANT SUBJECT CONSTRAINTS:
- Focus on Catholic Church history: saints, martyrs, popes, religious orders, missionaries, \
councils, and lay believers.
- Topics covering major historical splits and controversies are welcome and encouraged - the \
Great Schism of 1054, the Protestant Reformation and the historical circumstances that led to \
it, and the origins of other Christian traditions (Lutheran, Methodist, non-denominational, \
etc.) are all valid, engaging topics. When covering these:
  - Explain the REAL historical causes accurately and with genuine complexity - these events \
  had theological, political, economic, and cultural causes together, not a single simple \
  reason. Ground every specific claim in your Search results rather than a simplified popular \
  narrative.
  - Present what the historical reformers/participants actually believed and argued in their \
  own terms, accurately, even when explaining the Catholic Church's own historical response or \
  position - do not caricature or dismiss the other side's stated reasoning.
  - Do NOT frame the story as a verdict on which modern tradition is "right" or "wrong," and do \
  not characterize living denominations or their members negatively. The goal is accurate, \
  engaging history of how and why the split happened - not religious debate or persuasion aimed \
  at the viewer's own beliefs today.

You are telling ONE complete, true historical story in full. The story is broken into \
{TARGET_SEGMENT_COUNT_MIN}-{TARGET_SEGMENT_COUNT_MAX} short segments (each a 1-1.5 minute \
chapter, {MIN_SEGMENT_WORDS}-{MAX_SEGMENT_WORDS} words), which post first as a series, \
building up the full story with a "Follow for part N"-style hook (dynamically numbered - segment 1 says
"Follow for part 2", segment 2 says "Follow for part 3", and so on) at the end of every segment except the last. Days later, all segments are combined into one full-length video.

Each segment must be broken into {MIN_SCENES_PER_SEGMENT}-{MAX_SCENES_PER_SEGMENT} distinct \
scenes - write each scene's narration as a genuinely distinct beat or moment within the \
segment (not just an arbitrary chop of one continuous paragraph), since a separate visual \
will accompany each one. Do NOT include any visual descriptions, stage directions, or scene-\
setting notes in the narration text itself - just the spoken narration a viewer would hear.

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
        {{"narration": string}}
      ]
    }}
  ],
  "full_compilation": {{
    "title": string,
    "social_title": string,
    "caption": string
  }}
}}
Each segment's "scenes" array must contain {MIN_SCENES_PER_SEGMENT}-{MAX_SCENES_PER_SEGMENT} objects.
"segments" must contain {TARGET_SEGMENT_COUNT_MIN}-{TARGET_SEGMENT_COUNT_MAX} objects. Every segment except the last must end its final scene's narration with the exact phrase
"Follow for part N" where N is that segment's own number plus one (segment 1 -> "Follow for part 2",
segment 2 -> "Follow for part 3", etc.), and its caption must include that same phrase too. The last segment resolves the \
story with no follow phrase. "full_compilation" reuses the same title style for the eventual \
combined long-form video - do not write its own scenes; the full narration is just all segments' \
narration concatenated in order.
"""


VISUAL_SYSTEM_PROMPT = f"""You are a visual director assigning stick-figure scene visuals to an \
ALREADY-WRITTEN historical narration script. The text is fixed - your only job is to choose the \
visuals that best match what each individual scene's narration actually describes. Since figures \
are simple stick-figure illustrations (not photorealistic), each scene depicts what is actually \
HAPPENING using 1-3 fully-detailed figures, plus an optional background crowd:

- Use 1 figure for a solitary moment (someone praying alone, traveling, reflecting).
- Use 2 figures for a direct interaction (a trial before a judge, a conversation, a confrontation).
- Use 3 figures for a small group interaction (an arrest by two guards, a group discussion).
- Add "crowd_count" (a number from 0-{MAX_CROWD_COUNT}) when the narration describes a larger \
group - a mob, a gathering of bishops, a watching crowd - shown as simplified background figures \
behind the 1-3 detailed ones. Use 0 (or omit it) when no larger group is actually present.

Match the figures and setting to what THAT SPECIFIC scene's narration text actually describes -
read each scene individually and choose accordingly, rather than reusing the same visual for
every scene in a segment. Use "writing" for letter/journal-writing scenes, "raising_arms" for
blessing or proclamation moments, "grieving" for mourning, "book" for scripture/reading (distinct
from the "scroll" prop, used for letters), "torch" for night processions or searches. For settings:
use "arena" for amphitheater/execution scenes, "road" for travel/journey/exile scenes, "courtroom"
for trials/sentencing, "prison" for captivity, "temple" for worship/religious settings, "ship" for
sea voyages, "wall"/"hills" for general outdoor scenes. Each figure specifies its visuals using
ONLY these exact values - do not invent new ones:
- pose: one of {VALID_POSES}
- robe_color: one of {VALID_ROBE_COLORS}
- prop: one of {['"' + p + '"' for p in VALID_PROPS if p]} or null

Each scene (not each figure) also specifies:
- sky: one of {VALID_SKIES}
- landmark: one of {['"' + l + '"' for l in VALID_LANDMARKS if l]} or null

IMPORTANT: never pair robe_color="white" with sky="temple" or sky="plain", and never pair \
robe_color="green" with sky="night" - these specific combinations render as nearly the same \
shade and make the figure disappear into the background. Every other combination is fine.

Output ONLY a valid JSON array, no markdown fences, no commentary, with EXACTLY one object per
scene, in the SAME ORDER as the numbered scenes given to you, matching this schema exactly:
[
  {{
    "sky": string, "landmark": string | null,
    "crowd_count": number,
    "figures": [
      {{"pose": string, "robe_color": string, "prop": string | null}}
    ]
  }}
]
Each scene's "figures" array must contain {MIN_FIGURES_PER_SCENE}-{MAX_FIGURES_PER_SCENE} objects.
"""


SYSTEM_PROMPT = f"""You are a historian and scriptwriter creating short-form narration videos \
about real, documented Catholic Church history, spanning from the time of Christ and the \
apostles up through the present day. Your PRIMARY focus should be the ancient and early \
church era (roughly the 1st through 5th centuries) - martyrs, apostles, church fathers, \
early councils, and the earliest missionary movements - since this is the era you should \
draw from most often. Stories from later centuries, including the medieval, Counter-\
Reformation, and modern eras, are acceptable but should be featured less frequently than \
the ancient era. You have access to Google Search - use it to verify facts and ground your \
account in real historical sources, not invented details.

IMPORTANT SUBJECT CONSTRAINTS:
- Focus on Catholic Church history: saints, martyrs, popes, religious orders, missionaries, \
councils, and lay believers.
- Topics covering major historical splits and controversies are welcome and encouraged - the \
Great Schism of 1054, the Protestant Reformation and the historical circumstances that led to \
it, and the origins of other Christian traditions (Lutheran, Methodist, non-denominational, \
etc.) are all valid, engaging topics. When covering these:
  - Explain the REAL historical causes accurately and with genuine complexity - these events \
  had theological, political, economic, and cultural causes together, not a single simple \
  reason. Ground every specific claim in your Search results rather than a simplified popular \
  narrative.
  - Present what the historical reformers/participants actually believed and argued in their \
  own terms, accurately, even when explaining the Catholic Church's own historical response or \
  position - do not caricature or dismiss the other side's stated reasoning.
  - Do NOT frame the story as a verdict on which modern tradition is "right" or "wrong," and do \
  not characterize living denominations or their members negatively. The goal is accurate, \
  engaging history of how and why the split happened - not religious debate or persuasion aimed \
  at the viewer's own beliefs today.

You are telling ONE complete, true historical story in full. The story is broken into \
{TARGET_SEGMENT_COUNT_MIN}-{TARGET_SEGMENT_COUNT_MAX} short segments (each a 1-1.5 minute \
chapter, {MIN_SEGMENT_WORDS}-{MAX_SEGMENT_WORDS} words), which post first as a series, \
building up the full story with a "Follow for part N"-style hook (dynamically numbered - segment 1 says
"Follow for part 2", segment 2 says "Follow for part 3", and so on) at the end of every segment except the last. Days later, all segments are combined into one full-length video.

For the VISUAL side: each segment must be broken into {MIN_SCENES_PER_SEGMENT}-{MAX_SCENES_PER_SEGMENT} \
distinct scenes - a single unchanging image for a full 1-1.5 minute segment is visually flat, so \
real scene variety within each segment is required, not optional. Since figures are simple \
stick-figure illustrations (not photorealistic), each scene depicts what is actually HAPPENING \
using 1-3 fully-detailed figures, plus an optional background crowd:

- Use 1 figure for a solitary moment (someone praying alone, traveling, reflecting).
- Use 2 figures for a direct interaction (a trial before a judge, a conversation, a confrontation).
- Use 3 figures for a small group interaction (an arrest by two guards, a group discussion).
- Add "crowd_count" (a number from 0-{MAX_CROWD_COUNT}) when the narration describes a larger \
group - a mob, a gathering of bishops, a watching crowd - shown as simplified background figures \
behind the 1-3 detailed ones. Use 0 (or omit it) when no larger group is actually present.

Match the figures to what the narration for that scene actually describes - if the text says \
"her father begged her," show 2 figures, not 1. If it says "the crowd demanded his death," use \
crowd_count. Use "writing" for letter/journal-writing scenes, "raising_arms" for blessing or \
proclamation moments, "grieving" for mourning, "book" for scripture/reading (distinct from the \
"scroll" prop, used for letters), "torch" for night processions or searches, and the "prison" \
landmark for captivity scenes. Each figure specifies its visuals using ONLY these exact values \
- do not invent new ones:
- pose: one of {VALID_POSES}
- robe_color: one of {VALID_ROBE_COLORS}
- prop: one of {['"' + p + '"' for p in VALID_PROPS if p]} or null

Each scene (not each figure) also specifies:
- sky: one of {VALID_SKIES}
- landmark: one of {['"' + l + '"' for l in VALID_LANDMARKS if l]} or null

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
          "sky": string, "landmark": string | null,
          "crowd_count": number,
          "figures": [
            {{"pose": string, "robe_color": string, "prop": string | null}}
          ]
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
Each scene's "figures" array must contain {MIN_FIGURES_PER_SCENE}-{MAX_FIGURES_PER_SCENE} objects.
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
    return f"""Select ONE specific, real, well-documented Catholic Church history event or story \
to tell in full, then write the complete script for it. Favor the ancient/early church era \
(1st-5th century) most of the time, though later eras up to the present day are acceptable \
occasionally, including major historical splits and controversies (the Great Schism, the \
Reformation, the origins of other Christian traditions) - covered accurately and with genuine \
historical complexity, not as a one-sided verdict on any modern tradition.

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
def _call_gemini_narrative() -> str:
    """
    Pass 1: writes the narration text only. Uses Gemini's Google Search grounding
    tool so the model's account is checked against real, current web sources
    rather than relying only on training data - this is the pass that needs
    fact-checking, since it's the one making historical claims.
    """
    client = genai.Client(api_key=config.gemini_api_key)
    response = client.models.generate_content(
        model=config.gemini_text_model,
        contents=_append_performance_guidance(build_user_prompt()),
        config=types.GenerateContentConfig(
            system_instruction=NARRATIVE_SYSTEM_PROMPT,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        ),
    )
    return response.text


@retry_with_backoff(max_retries=config.max_retries, base_delay=config.retry_base_delay)
def _call_gemini_visual(flat_scenes: list[dict]) -> str:
    """
    Pass 2: given the ALREADY-WRITTEN, fixed narration text, assigns matching
    visuals scene by scene. No search grounding here - this is a pure matching/
    reasoning task against a fixed vocabulary, not a fact-verification task, so
    it doesn't need real-time web access the way Pass 1 does.
    """
    client = genai.Client(api_key=config.gemini_api_key)
    response = client.models.generate_content(
        model=config.gemini_text_model,
        contents=build_visual_user_prompt(flat_scenes),
        config=types.GenerateContentConfig(system_instruction=VISUAL_SYSTEM_PROMPT),
    )
    return response.text


def _validate_figure(figure: dict, sky: str):
    if figure["pose"] not in VALID_POSES:
        raise ValueError(f"Invalid pose: {figure['pose']!r}")
    if figure["robe_color"] not in VALID_ROBE_COLORS:
        raise ValueError(f"Invalid robe_color: {figure['robe_color']!r}")
    if figure.get("prop") not in VALID_PROPS:
        raise ValueError(f"Invalid prop: {figure.get('prop')!r}")
    if (figure["robe_color"], sky) in LOW_CONTRAST_PAIRS:
        raise ValueError(
            f"robe_color={figure['robe_color']!r} on sky={sky!r} renders as nearly "
            f"the same shade (low contrast) - choose a different robe color or sky for this scene"
        )


def _validate_scene(scene: dict):
    if scene["sky"] not in VALID_SKIES:
        raise ValueError(f"Invalid sky: {scene['sky']!r}")
    if scene.get("landmark") not in VALID_LANDMARKS:
        raise ValueError(f"Invalid landmark: {scene.get('landmark')!r}")

    figures = scene.get("figures")
    if not figures:
        raise ValueError("Scene is missing a non-empty 'figures' list")
    if not (MIN_FIGURES_PER_SCENE <= len(figures) <= MAX_FIGURES_PER_SCENE):
        raise ValueError(
            f"Scene has {len(figures)} figure(s), expected {MIN_FIGURES_PER_SCENE}-{MAX_FIGURES_PER_SCENE}"
        )
    for figure in figures:
        _validate_figure(figure, scene["sky"])

    crowd_count = scene.get("crowd_count", 0) or 0
    if not (0 <= crowd_count <= MAX_CROWD_COUNT):
        raise ValueError(f"crowd_count {crowd_count} out of range 0-{MAX_CROWD_COUNT}")


def _validate_structure_and_text(data: dict, require_visuals: bool):
    """
    Shared structural/text checks (segment count, word count, scene count,
    follow-phrase placement, topic/compilation presence) used for BOTH the
    narrative-only Pass 1 output and the final merged result. `require_visuals`
    additionally runs _validate_scene on each scene - skipped for Pass 1, where
    scenes don't have visual fields yet.
    """
    segments = data["segments"]
    if not (TARGET_SEGMENT_COUNT_MIN <= len(segments) <= TARGET_SEGMENT_COUNT_MAX):
        raise ValueError(f"Expected {TARGET_SEGMENT_COUNT_MIN}-{TARGET_SEGMENT_COUNT_MAX} segments, got {len(segments)}")

    for i, seg in enumerate(segments):
        word_count = sum(len(sc["narration"].split()) for sc in seg["scenes"])
        if word_count < MIN_SEGMENT_WORDS:
            raise ValueError(f"Segment {i+1} has {word_count} words, under the {MIN_SEGMENT_WORDS} minimum")
        if word_count > MAX_SEGMENT_WORDS:
            raise ValueError(f"Segment {i+1} has {word_count} words, over the {MAX_SEGMENT_WORDS} maximum")
        if not (MIN_SCENES_PER_SEGMENT <= len(seg["scenes"]) <= MAX_SCENES_PER_SEGMENT):
            raise ValueError(
                f"Segment {i+1} has {len(seg['scenes'])} scene(s), expected "
                f"{MIN_SCENES_PER_SEGMENT}-{MAX_SCENES_PER_SEGMENT} for visual variety within a 1-1.5 minute segment"
            )
        if require_visuals:
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


def _validate_narrative(raw: str) -> dict:
    """Validates Pass 1's output: text/structure only, no visual fields exist yet."""
    data = json.loads(_strip_code_fences(raw))
    _validate_structure_and_text(data, require_visuals=False)
    return data


def _flatten_scenes(narrative_data: dict) -> list[dict]:
    """Flat list of every scene across every segment, in order - the exact
    sequence Pass 2 is asked to tag, so merging back can zip by position."""
    flat = []
    for seg in narrative_data["segments"]:
        flat.extend(seg["scenes"])
    return flat


def build_visual_user_prompt(flat_scenes: list[dict]) -> str:
    numbered = "\n".join(f"{i+1}. {sc['narration']}" for i, sc in enumerate(flat_scenes))
    return f"""Here are {len(flat_scenes)} numbered scenes from an already-written historical \
narration script, in order. Assign visuals to each one individually, based on what THAT \
scene's text actually describes.

{numbered}

Return ONLY the JSON array described in your instructions, with exactly {len(flat_scenes)} \
objects in the same order as the numbered scenes above, nothing else."""


def _validate_visual_tags(raw: str, expected_count: int) -> list[dict]:
    tags = json.loads(_strip_code_fences(raw))
    if not isinstance(tags, list):
        raise ValueError("Visual tagging response is not a JSON array")
    if len(tags) != expected_count:
        raise ValueError(f"Expected {expected_count} visual tag objects, got {len(tags)}")
    for i, tag in enumerate(tags):
        try:
            _validate_scene({**tag, "narration": ""})
        except ValueError as e:
            raise ValueError(f"Visual tag {i+1}: {e}")
    return tags


def _merge_narrative_and_visuals(narrative_data: dict, visual_tags: list[dict]) -> dict:
    """Zips the flat visual-tag list back onto the narrative's scenes by position -
    both were generated in the same flattened order, so index i of one always
    corresponds to index i of the other."""
    merged = json.loads(json.dumps(narrative_data))  # deep copy
    flat_index = 0
    for seg in merged["segments"]:
        for scene in seg["scenes"]:
            tag = visual_tags[flat_index]
            scene["sky"] = tag["sky"]
            scene["landmark"] = tag.get("landmark")
            scene["crowd_count"] = tag.get("crowd_count", 0)
            scene["figures"] = tag["figures"]
            flat_index += 1
    return merged


def _validate_and_parse(raw: str) -> dict:
    """Retained for any external caller still passing a single already-complete
    JSON blob (e.g. a hand-authored local fallback story) - validates the FULL
    merged schema including visuals, same as before this file used two passes."""
    data = json.loads(_strip_code_fences(raw))
    _validate_structure_and_text(data, require_visuals=True)
    return data


def generate_church_history_story() -> dict:
    """
    Two-pass generation: Pass 1 writes the search-grounded narration text only
    (no visual guessing while also inventing narrative). Pass 2, given that
    ALREADY-FIXED text, assigns visuals scene by scene - a focused matching task
    rather than one model simultaneously writing history AND guessing pictures.
    Both passes are validated independently, then merged and given one final
    structural check. Raises on failure (caller handles fallback to local pool).
    """
    logger.info("Generating story text (Pass 1/2, search-grounded) via Gemini")
    narrative_raw = _call_gemini_narrative()
    narrative_data = _validate_narrative(narrative_raw)
    logger.info(
        f"Narrative ready: topic={narrative_data['topic']!r}, {len(narrative_data['segments'])} segments"
    )

    flat_scenes = _flatten_scenes(narrative_data)
    logger.info(f"Generating matching visuals (Pass 2/2) for {len(flat_scenes)} scenes via Gemini")
    visual_raw = _call_gemini_visual(flat_scenes)
    visual_tags = _validate_visual_tags(visual_raw, expected_count=len(flat_scenes))

    merged = _merge_narrative_and_visuals(narrative_data, visual_tags)
    _validate_structure_and_text(merged, require_visuals=True)

    logger.info(
        f"Story ready: topic={merged['topic']!r}, {len(merged['segments'])} segments, "
        f"word counts: {[sum(len(sc['narration'].split()) for sc in s['scenes']) for s in merged['segments']]}"
    )
    return merged
