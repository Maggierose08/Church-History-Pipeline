import logging
import random
import subprocess

logger = logging.getLogger("video_pipeline")


def _run_ffmpeg(cmd: list[str]):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg command failed (exit {result.returncode}): {' '.join(cmd)}\n"
            f"--- stderr (last 2000 chars) ---\n{result.stderr[-2000:]}"
        )


# Each style is a (zoom_expr, x_expr, y_expr) triple. Zoom is always a slow, gentle
# creep (never jarring) - style controls WHERE the zoom is anchored/drifting toward,
# for visual variety across scenes rather than every clip doing the identical motion.
PAN_STYLES = {
    "center_in": (
        "min(zoom+0.0012,1.25)",
        "iw/2-(iw/zoom/2)",
        "ih*0.62-(ih/zoom/2)",
    ),
    "drift_left": (
        "min(zoom+0.0010,1.2)",
        "iw*0.42-(iw/zoom/2)",
        "ih*0.62-(ih/zoom/2)",
    ),
    "drift_right": (
        "min(zoom+0.0010,1.2)",
        "iw*0.58-(iw/zoom/2)",
        "ih*0.62-(ih/zoom/2)",
    ),
    "zoom_out": (
        "if(eq(on,1),1.25,max(zoom-0.0012,1.0))",
        "iw/2-(iw/zoom/2)",
        "ih*0.62-(ih/zoom/2)",
    ),
}


def build_scene_clip(image_path: str, duration: float, out_path: str,
                      width: int = 1080, height: int = 1920, fps: int = 30,
                      style: str = None) -> str:
    """
    Turns one still image into a video clip with a slow Ken Burns pan/zoom over
    `duration` seconds. `style` picks the pan direction/style (random if not given) -
    the zoom is always gentle and always stays anchored around the lower-middle of
    the frame (ih*0.62), matching where figures are actually positioned in the
    generated scenes, rather than ffmpeg's default top-left anchor which drifts
    toward empty sky.
    """
    style = style or random.choice(list(PAN_STYLES.keys()))
    zoom_expr, x_expr, y_expr = PAN_STYLES[style]
    frames = max(1, int(round(duration * fps)))

    _run_ffmpeg([
        "ffmpeg", "-y", "-loop", "1", "-i", image_path, "-t", str(duration),
        "-vf", (
            f"scale={width * 2}:{height * 2},"
            f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':d={frames}:s={width}x{height}:fps={fps}"
        ),
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", out_path,
    ])
    return out_path
