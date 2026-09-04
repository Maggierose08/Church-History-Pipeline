import logging

import requests
from google import genai
from PIL import Image, ImageDraw, ImageFont

from config import config
from retry_utils import retry_with_backoff

logger = logging.getLogger("video_pipeline")


@retry_with_backoff(max_retries=config.max_retries, base_delay=config.retry_base_delay)
def _generate_gemini_thumbnail(title: str, output_path: str):
    client = genai.Client(api_key=config.gemini_api_key)
    prompt = (
        f'A dramatic, eye-catching vertical 9:16 thumbnail illustration for a short-form '
        f'historical narration video, simple stick-figure / minimalist illustration style '
        f'with muted historical color tones. No text overlay. Theme: "{title}"'
    )
    response = client.models.generate_content(model=config.gemini_image_model, contents=prompt)
    for part in response.candidates[0].content.parts:
        if part.inline_data:
            with open(output_path, "wb") as f:
                f.write(part.inline_data.data)
            return
    raise RuntimeError("Gemini response contained no image data")


@retry_with_backoff(max_retries=2, base_delay=2.0)
def _generate_pollinations_thumbnail(title: str, output_path: str):
    prompt = f"simple stick figure minimalist illustration, historical, vertical thumbnail, {title}"
    params = {"width": 1080, "height": 1920, "nologo": "true"}
    if config.pollinations_api_key:
        params["token"] = config.pollinations_api_key
    resp = requests.get(f"https://image.pollinations.ai/prompt/{requests.utils.quote(prompt)}", params=params, timeout=60)
    resp.raise_for_status()
    with open(output_path, "wb") as f:
        f.write(resp.content)


def _generate_local_fallback_thumbnail(title: str, output_path: str):
    img = Image.new("RGB", (1080, 1920), color=(232, 228, 218))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 70)
    except Exception:
        font = ImageFont.load_default()
    words = title.split()
    lines, current = [], ""
    for w in words:
        test = f"{current} {w}".strip()
        if draw.textlength(test, font=font) > 950:
            lines.append(current)
            current = w
        else:
            current = test
    if current:
        lines.append(current)
    y = 900 - (len(lines) * 45)
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text(((1080 - w) / 2, y), line, font=font, fill=(30, 30, 30))
        y += 90
    img.save(output_path)


def generate_thumbnail(title: str, output_path: str) -> dict:
    logger.info(f"Generating thumbnail for title: '{title}'")
    if config.gemini_api_key:
        try:
            _generate_gemini_thumbnail(title, output_path)
            logger.info(f"Thumbnail saved to {output_path}")
            return {"thumbnail_path": output_path}
        except Exception as e:
            logger.warning(f"Gemini thumbnail generation failed after retries: {e}")
    logger.info("Falling back to Pollinations for thumbnail generation")
    try:
        _generate_pollinations_thumbnail(title, output_path)
        logger.info(f"Thumbnail saved to {output_path}")
        return {"thumbnail_path": output_path}
    except Exception as e:
        logger.warning(f"Pollinations thumbnail generation failed: {e}")
    logger.info("Falling back to local Pillow-rendered thumbnail")
    _generate_local_fallback_thumbnail(title, output_path)
    return {"thumbnail_path": output_path}
