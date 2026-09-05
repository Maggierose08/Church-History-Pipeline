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

# Images change roughly every 2-3 seconds throughout a segment, not just once or
# twice per scene - this is how often a new still/Ken-Burns-beat is generated.
TARGET_BEAT_SECONDS = 2.5


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


# Cycle of 4 distinct visual variations (position nudge + facing) applied in
# sequence across a scene's beats, so a scene lasting many beats doesn't just
# flip back and forth between 2 identical states repeatedly.
_VARIANT_OFFSETS = {0: 0.0, 1: 0.05, 2: 0.0, 3: -0.05}
_VARIANT_FLIP = {0: False, 1: True, 2: False, 3: True}
NUM_VISUAL_VARIANTS = 4


def _scene_to_image(scene: dict, output_path: str, variant: int = 0):
    """
    Converts one scene's visual spec (1-3 figures + optional background crowd +
    sky/landmark) into a rendered stick-figure still. `variant` cycles through 4
    distinct position/facing states (see _VARIANT_OFFSETS/_VARIANT_FLIP) so a scene
    split into many short beats shows real visual variety rather than repeating the
    same 2 states over and over, without needing new story content.
    """
    has_landmark = bool(scene.get("landmark"))
    figure_specs = [
        {"pose": f["pose"], "robe_color": f["robe_color"], "prop": f.get("prop")}
        for f in scene["figures"]
    ]
    positioned = figure_layout.position_figures(
        figure_specs, config.video_width, config.video_height, has_landmark
    )

    v = variant % NUM_VISUAL_VARIANTS
    offset_frac = _VARIANT_OFFSETS[v]
    flip = _VARIANT_FLIP[v]
    if offset_frac or flip:
        center_x = config.video_width // 2
        for fig in positioned:
            if offset_frac:
                direction = 1 if fig["x"] >= center_x else -1
                fig["x"] += int(config.video_width * offset_frac) * direction
            if flip:
                fig["facing"] *= -1

    img = stick_figures.draw_scene(
        width=config.video_width,
        height=config.video_height,
        sky=scene["sky"],
        landmark=scene.get("landmark"),
        figures=positioned,
    )

    crowd_count = scene.get("crowd_count", 0) or 0
    if crowd_count > 0:
        draw = ImageDraw.Draw(img)
        ground_y = int(config.video_height * 0.82)
        stick_figures.draw_crowd_silhouettes(draw, crowd_count, config.video_width, ground_y)

    img.save(output_path)


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

    # Each scene is split into ~2-3 second beats (not just 2 halves) - same pose/robe/
    # sky/landmark/prop (the actual story content is unchanged), cycling through 4
    # position/facing variants, so the image visibly changes every 2-3 seconds
    # throughout the whole segment without requiring new narration to be written.
    segment_clip_paths = []
    clip_index = 0
    for i, (scene, duration) in enumerate(zip(scenes, scene_durations)):
        num_beats = max(1, round(duration / TARGET_BEAT_SECONDS))
        beat_duration = duration / num_beats
        for beat in range(num_beats):
            image_path = f"{output_dir}/scene_{i}_{beat}.png"
            _scene_to_image(scene, image_path, variant=beat)
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
