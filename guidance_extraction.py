import json
import logging

from google import genai

from config import config

logger = logging.getLogger("video_pipeline")

GUIDANCE_PROMPT_TEMPLATE = """You are analyzing performance data for a series of short-form \
church history narration videos, to find patterns that can guide future topic selection and \
storytelling style.

Here are the TOP performing videos this week (highest engagement):
{top_list}

Here are the BOTTOM performing videos this week (lowest engagement):
{bottom_list}

Based on comparing these two groups, identify 3-5 short, concrete, actionable patterns. Be \
specific, not generic. If the two groups don't show any clear pattern, say so plainly instead \
of inventing one.

Output ONLY a JSON object with this exact schema, no markdown fences, no commentary:
{{"guidance": "2-4 sentences of concrete, actionable guidance, written to be pasted directly into a script-writing prompt as extra context."}}
"""


def _format_video_list(records: list[dict]) -> str:
    return "\n".join(f"- \"{r['topic']}\" (title: \"{r['title']}\") - score: {r['score']:.0f}" for r in records)


def extract_guidance(top_performers: list[dict], bottom_performers: list[dict]) -> str:
    if not config.gemini_api_key:
        return "No guidance available this week (GEMINI_API_KEY not configured)."
    prompt = GUIDANCE_PROMPT_TEMPLATE.format(
        top_list=_format_video_list(top_performers), bottom_list=_format_video_list(bottom_performers)
    )
    try:
        client = genai.Client(api_key=config.gemini_api_key)
        response = client.models.generate_content(
            model=config.gemini_text_model, contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        data = json.loads(response.text.strip())
        return data["guidance"]
    except Exception as e:
        logger.warning(f"Guidance extraction failed, skipping this week's update: {e}")
        return "No guidance available this week (analysis failed - see logs)."
