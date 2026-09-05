import logging
import os
import subprocess

from config import config
from retry_utils import retry_with_backoff
import ass_captions
import stick_figures
from kenburns import build_scene_clip

logger = logging.getLogger("video_pipeline")


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


def _scene_to_image(scene: dict, output_path: str, variant: int = 0):
    """
    Converts one scene's visual spec (pose/robe_color/sky/landmark/prop) into a
    rendered stick-figure still. `variant` (0 or 1) shifts facing direction and
    horizontal position slightly - used to produce a second, genuinely different
    still from the SAME scene data, so the image can change partway through a
    scene's screen time without needing new story content or narration.
    """
    has_landmark = bool(scene.get("landmark"))
    scale = 2.2 if has_landmark else 2.6
    figure_y = int(config.video_height * 0.68)
    facing = 1 if variant == 0 else -1
    x_offset = 0 if variant == 0 else int(config.video_width * 0.08)

    img = stick_figures.draw_scene(
        width=config.video_width,
        height=config.video_height,
        sky=scene["sky"],
        landmark=scene.get("landmark"),
        figures=[{
            "pose": scene["pose"],
            "x": config.video_width // 2 + x_offset,
            "y": figure_y,
            "scale": scale,
            "facing": facing,
            "robe_color": scene["robe_color"],
            "prop": scene.get("prop"),
        }],
    )
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

    # Each scene is split into 2 visual sub-beats of equal duration - same pose/robe/
    # sky/landmark/prop (the actual story content is unchanged), but a shifted facing
    # and position, so the image visibly changes roughly twice as often as before
    # without requiring new narration or additional scenes to be written.
    segment_clip_paths = []
    clip_index = 0
    for i, (scene, duration) in enumerate(zip(scenes, scene_durations)):
        half_duration = duration / 2
        for variant in (0, 1):
            image_path = f"{output_dir}/scene_{i}_{variant}.png"
            _scene_to_image(scene, image_path, variant=variant)
            clip_path = f"{output_dir}/kb_clip_{clip_index}.mp4"
            build_scene_clip(image_path, half_duration, clip_path, width=config.video_width, height=config.video_height)
            segment_clip_paths.append(clip_path)
            clip_index += 1
        logger.info(f"Rendered scene {i+1}/{len(scenes)} as 2 sub-beats ({duration:.1f}s total, pose={scene['pose']})")

    concat_path = f"{output_dir}/concatenated.mp4"
    _concat_segments(segment_clip_paths, f"{output_dir}/concat_list.txt", concat_path)
    logger.info(f"Concatenated {len(segment_clip_paths)} scene clip(s)")

    final_path = f"{output_dir}/final_video.mp4"
    _mux_audio_and_burn_subtitles(concat_path, audio_path, ass_path, final_path)
    logger.info(f"Rendered video (stick-figure Ken Burns) at {final_path}")

    return {"video_path": final_path, "subtitle_active_color": active_color, "subtitle_line_color": line_color}
