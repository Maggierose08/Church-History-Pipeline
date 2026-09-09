import logging
import subprocess

logger = logging.getLogger("video_pipeline")


def _run_ffmpeg(cmd: list[str]):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg command failed (exit {result.returncode}): {' '.join(cmd)}\n"
            f"--- stderr (last 2000 chars) ---\n{result.stderr[-2000:]}"
        )


def build_scene_clip(image_path: str, duration: float, out_path: str,
                      width: int = 1080, height: int = 1920, fps: int = 30,
                      style: str = None) -> str:
    """
    Turns one still image into a static video clip for `duration` seconds - no
    pan or zoom motion at all, per explicit request to remove the Ken Burns effect
    entirely. `style` is accepted but ignored, kept only so existing call sites
    don't need to change their arguments.
    """
    _run_ffmpeg([
        "ffmpeg", "-y", "-loop", "1", "-i", image_path, "-t", str(duration),
        "-vf", f"scale={width}:{height}",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-r", str(fps), out_path,
    ])
    return out_path
