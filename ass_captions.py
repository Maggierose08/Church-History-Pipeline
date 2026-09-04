import logging

from config import config

logger = logging.getLogger("video_pipeline")


def _hex_to_ass_color(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}&".upper()


def _format_timestamp(seconds: float) -> str:
    cs = round(seconds * 100)
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


BASE_Y_FRACTION = {"top": 0.15, "middle": 0.5, "bottom": 0.85}


def build_ass(words: list[dict], output_path: str, active_color: str = None, line_color: str = None) -> str:
    active_color_ass = _hex_to_ass_color(active_color or "#FF0000")
    line_color_ass = _hex_to_ass_color(line_color or "#FFFFFF")
    bold = "-1" if config.subtitle_bold else "0"

    base_fraction = BASE_Y_FRACTION.get(config.subtitle_vertical_position, 0.5)
    pos_x = config.video_width // 2
    pos_y = int(config.video_height * base_fraction) + config.subtitle_vertical_offset_px

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {config.video_width}
PlayResY: {config.video_height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{config.subtitle_font_family},{config.subtitle_font_size},{line_color_ass},{active_color_ass},&H00000000&,&H00000000&,{bold},0,0,0,100,100,0,0,1,2,1,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    n = config.subtitle_max_words_per_line
    for i in range(0, len(words), n):
        group = words[i : i + n]
        if not group:
            continue
        line_start = group[0]["start"]
        line_end = group[-1]["end"]
        text_parts = [f"{{\\an5\\pos({pos_x},{pos_y})}}"]
        for w in group:
            duration_cs = max(1, round((w["end"] - w["start"]) * 100))
            text_parts.append(f"{{\\k{duration_cs}}}{w['word']} ")
        text = "".join(text_parts).strip()
        lines.append(f"Dialogue: 0,{_format_timestamp(line_start)},{_format_timestamp(line_end)},Default,,0,0,0,,{text}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(lines))
        f.write("\n")

    logger.info(f"Built ASS captions with {len(lines)} lines at {output_path}")
    return output_path
