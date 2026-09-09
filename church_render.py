import logging
import os
import subprocess

from PIL import ImageDraw

from config import config
from retry_utils import retry_with_backoff
import ass_captions
import stick_figures
import figure_layout
from kenburns import build_scene_clip

logger = logging.getLogger("video_pipeline")

# Images change completely every ~5 seconds throughout a segment - a genuinely
# different static framing each time (not a zoom/pan animation, and not just the
# same shot mirrored left-right).
TARGET_BEAT_SECONDS = 5.0

# The scene is rendered once at this oversized canvas, then each beat crops a
# DIFFERENT static window from that same render - producing genuinely different
# shots (a wide view, a close view on the figures, background-emphasis, left/
# right framing) from a single underlying piece of art, with no zoom/pan motion
# within any individual clip.
OVERSIZE_FACTOR = 1.5

# Each preset is (crop_width_frac, crop_height_frac, x_center_frac, y_center_frac)
# as fractions of the oversized canvas - x/y center is where that crop window is
# positioned. Cycled through in order so consecutive beats are never identical.
FRAMING_PRESETS = [
    (1.0, 1.0, 0.5, 0.5),      # wide: the full oversized canvas, nothing cropped away
    (0.55, 0.55, 0.5, 0.62),   # close on the figures
    (0.75, 0.75, 0.32, 0.55),  # left-weighted medium shot
    (0.75, 0.75, 0.68, 0.55),  # right-weighted medium shot
    (0.85, 0.85, 0.5, 0.30),   # background-emphasis: shifted up toward sky/landmark
]


def _run_ffmpeg(cmd: list[str]):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg command failed (exit {result.returncode}): {' '.join(cmd)}\n"
            f"--- stderr (last 2000 chars) ---\n{result.stderr[-2000:]}"
        )


def _concat_segments(segment_paths: list[str], list_file: str, out_path: str):
    with open(list_file, "w") as f:
        for p in segment_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")
    _run_ffmpeg(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", out_path])


def _mux_audio_and_burn_subtitles(video_path: str, audio_path: str, ass_path: str, out_path: str):
    _run_ffmpeg([
        "ffmpeg", "-y", "-i", video_path, "-i", audio_path, "-vf", f"ass={ass_path}",
        "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k", "-shortest", out_path,
    ])


def _render_oversized_scene(scene: dict):
    """
    Renders one scene's visual spec (1-3 figures + optional background crowd +
    sky/landmark) ONCE, at an oversized canvas (OVERSIZE_FACTOR bigger than the
    final video resolution). Different beats then crop different windows from
    this same oversized render - see _crop_framing.
    """
    ow = int(config.video_width * OVERSIZE_FACTOR)
    oh = int(config.video_height * OVERSIZE_FACTOR)
    has_landmark = bool(scene.get("landmark"))
    figure_specs = [
        {"pose": f["pose"], "robe_color": f["robe_color"], "prop": f.get("prop")}
        for f in scene["figures"]
    ]
    positioned = figure_layout.position_figures(figure_specs, ow, oh, has_landmark)

    img = stick_figures.draw_scene(
        width=ow, height=oh, sky=scene["sky"], landmark=scene.get("landmark"), figures=positioned,
    )

    crowd_count = scene.get("crowd_count", 0) or 0
    if crowd_count > 0:
        draw = ImageDraw.Draw(img)
        ground_y = int(oh * 0.82)
        stick_figures.draw_crowd_silhouettes(draw, crowd_count, ow, ground_y)

    return img


def _crop_framing(oversized_img, preset_index: int):
    """
    Crops ONE static window from the oversized render, per FRAMING_PRESETS, then
    resizes it to the final target resolution. Each preset produces a genuinely
    different-looking still (different crop position/size) from the SAME
    underlying artwork - no zoom/pan animation within the resulting clip, just a
    different fixed shot each time.
    """
    ow, oh = oversized_img.size
    w_frac, h_frac, cx_frac, cy_frac = FRAMING_PRESETS[preset_index % len(FRAMING_PRESETS)]

    crop_w = int(ow * w_frac)
    crop_h = int(oh * h_frac)
    cx = int(ow * cx_frac)
    cy = int(oh * cy_frac)

    left = max(0, min(ow - crop_w, cx - crop_w // 2))
    top = max(0, min(oh - crop_h, cy - crop_h // 2))
    cropped = oversized_img.crop((left, top, left + crop_w, top + crop_h))
    return cropped.resize((config.video_width, config.video_height))


def render_segment_video(segment: dict, audio_path: str, timestamps_path: str, run_id: str, output_dir: str) -> dict:
    """
    Renders one segment (a list of scenes, each with narration + visual spec) into a
    final video: stick-figure image per scene -> Ken Burns clip -> concatenated ->
    audio muxed -> subtitles burned. Scene durations are derived by evenly dividing
    the segment's total audio duration across its scenes, weighted by each scene's
    narration word count (a scene with more words gets proportionally more screen time).
    """
    import json
    with open(timestamps_path) as f:
        timestamps = json.load(f)
    words = timestamps["words"]
    total_duration = words[-1]["end"] if words else 50.0

    scenes = segment["scenes"]
    word_counts = [len(sc["narration"].split()) for sc in scenes]
    total_words = sum(word_counts) or 1
    scene_durations = [total_duration * (wc / total_words) for wc in word_counts]

    active_color, line_color = config.pick_subtitle_color_pair()
    ass_path = f"{output_dir}/captions.ass"
    ass_captions.build_ass(words, ass_path, active_color=active_color, line_color=line_color)

    # Each scene is rendered ONCE at an oversized canvas, then split into ~5-second
    # beats, each showing a genuinely DIFFERENT static crop/framing of that same
    # render (wide, close, left, right, background-emphasis) - real visual variety
    # every 5 seconds, not a mirrored repeat of the same shot, and no zoom/pan
    # motion within any individual clip.
    segment_clip_paths = []
    clip_index = 0
    for i, (scene, duration) in enumerate(zip(scenes, scene_durations)):
        oversized = _render_oversized_scene(scene)
        num_beats = max(1, round(duration / TARGET_BEAT_SECONDS))
        beat_duration = duration / num_beats
        for beat in range(num_beats):
            framed = _crop_framing(oversized, beat)
            image_path = f"{output_dir}/scene_{i}_{beat}.png"
            framed.save(image_path)
            clip_path = f"{output_dir}/kb_clip_{clip_index}.mp4"
            build_scene_clip(image_path, beat_duration, clip_path, width=config.video_width, height=config.video_height)
            segment_clip_paths.append(clip_path)
            clip_index += 1
        poses = [f["pose"] for f in scene["figures"]]
        logger.info(f"Rendered scene {i+1}/{len(scenes)} as {num_beats} beat(s) of ~{beat_duration:.1f}s each ({duration:.1f}s total, {len(poses)} figure(s): {poses}, crowd={scene.get('crowd_count', 0)})")

    concat_path = f"{output_dir}/concatenated.mp4"
    _concat_segments(segment_clip_paths, f"{output_dir}/concat_list.txt", concat_path)
    logger.info(f"Concatenated {len(segment_clip_paths)} scene clip(s)")

    final_path = f"{output_dir}/final_video.mp4"
    _mux_audio_and_burn_subtitles(concat_path, audio_path, ass_path, final_path)
    logger.info(f"Rendered video (stick-figure Ken Burns) at {final_path}")

    return {"video_path": final_path, "subtitle_active_color": active_color, "subtitle_line_color": line_color}
