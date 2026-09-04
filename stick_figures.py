import math

from PIL import Image, ImageDraw

LINE_WIDTH = 10
FIGURE_COLOR = (25, 25, 25)

BG_SKY_COLORS = {
    "desert": (235, 215, 165),
    "temple": (210, 200, 220),
    "sea": (180, 212, 225),
    "night": (35, 40, 65),
    "plain": (232, 228, 218),
}

ROBE_COLORS = {
    "white": (245, 242, 235),
    "red": (165, 45, 40),
    "blue": (50, 75, 130),
    "brown": (110, 80, 55),
    "purple": (95, 55, 110),
    "green": (60, 100, 70),
}


def _draw_head(draw, cx, cy, r):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=FIGURE_COLOR, width=LINE_WIDTH)


def _limb(draw, x1, y1, x2, y2, width=LINE_WIDTH):
    draw.line([x1, y1, x2, y2], fill=FIGURE_COLOR, width=width)


def _draw_robe(draw, x, y, hip_y, width_top, width_bottom, color):
    rgb = ROBE_COLORS.get(color, ROBE_COLORS["white"])
    draw.polygon(
        [
            (x - width_top, y),
            (x + width_top, y),
            (x + width_bottom, hip_y),
            (x - width_bottom, hip_y),
        ],
        fill=rgb,
        outline=FIGURE_COLOR,
    )


def _draw_prop(draw, prop, x, y, hip_y, scale, facing):
    s = scale
    f = facing
    if prop == "staff":
        top_x, top_y = x + 55 * s * f, y - 60 * s
        bot_x, bot_y = x + 45 * s * f, hip_y + 60 * s
        draw.line([top_x, top_y, bot_x, bot_y], fill=(90, 65, 40), width=int(LINE_WIDTH * 0.8))
    elif prop == "scroll":
        draw.rounded_rectangle(
            [x + 20 * s * f, y + 35 * s, x + 50 * s * f, y + 58 * s],
            radius=6, fill=(230, 218, 190), outline=FIGURE_COLOR, width=3,
        )
    elif prop == "cross":
        cx, cy = x - 55 * s * f, y - 20 * s
        draw.line([cx, cy - 30 * s, cx, cy + 30 * s], fill=(80, 60, 45), width=int(LINE_WIDTH * 0.8))
        draw.line([cx - 15 * s, cy - 12 * s, cx + 15 * s, cy - 12 * s], fill=(80, 60, 45), width=int(LINE_WIDTH * 0.8))


def draw_pose(draw, pose: str, x: int, y: int, scale: float = 1.0, facing: int = 1,
              robe_color: str = "white", prop: str = None):
    """
    Draws one stick figure. (x, y) = neck/shoulder position.
    Layer order: robe silhouette -> lower-body limbs (mostly hidden by robe, only feet
    peek out) -> head -> arms (drawn last, positioned to clear the head cleanly).
    """
    s = scale
    f = facing
    head_r = 32 * s

    # Kneeling compresses the torso-to-hip distance (person is lower to the ground);
    # everyone else uses the standard standing torso length.
    hip_y = y + (70 * s if pose == "kneeling" else 100 * s)

    _draw_robe(draw, x, y, hip_y, 22 * s, 55 * s, robe_color)

    # Lower body: only small feet marks peek below the robe hem, avoiding leg lines
    # that would otherwise cross messily through the colored robe shape.
    if pose == "kneeling":
        _limb(draw, x - 12 * s * f, hip_y, x + 18 * s * f, hip_y + 6 * s, width=int(LINE_WIDTH * 0.7))
    elif pose == "sitting":
        _limb(draw, x, hip_y, x + 45 * s * f, hip_y, width=int(LINE_WIDTH * 0.8))
        _limb(draw, x + 45 * s * f, hip_y, x + 45 * s * f, hip_y + 50 * s, width=int(LINE_WIDTH * 0.8))
    elif pose == "walking":
        _limb(draw, x - 8 * s * f, hip_y, x + 32 * s * f, hip_y + 15 * s, width=int(LINE_WIDTH * 0.7))
        _limb(draw, x - 8 * s * f, hip_y, x - 25 * s * f, hip_y + 20 * s, width=int(LINE_WIDTH * 0.7))
    else:  # standing
        _limb(draw, x - 10 * s * f, hip_y, x + 12 * s * f, hip_y + 15 * s, width=int(LINE_WIDTH * 0.7))
        _limb(draw, x - 10 * s * f, hip_y, x - 20 * s * f, hip_y + 15 * s, width=int(LINE_WIDTH * 0.7))

    _draw_head(draw, x, y - head_r - 4 * s, head_r)

    # Arms - each pose's arm geometry is chosen to stay clearly below the head's
    # bottom edge (y - 4*s), so nothing crosses through the face.
    shoulder_y = y + 20 * s
    if pose == "praying":
        _limb(draw, x, shoulder_y, x + 16 * s * f, shoulder_y - 30 * s)
        _limb(draw, x, shoulder_y, x - 16 * s * f, shoulder_y - 30 * s)
    elif pose == "teaching":
        _limb(draw, x + 10 * s * f, shoulder_y, x + 58 * s * f, shoulder_y - 20 * s)
        _limb(draw, x, shoulder_y, x - 25 * s * f, shoulder_y + 30 * s)
    elif pose == "pointing":
        _limb(draw, x + 8 * s * f, shoulder_y, x + 62 * s * f, shoulder_y - 25 * s)
        _limb(draw, x, shoulder_y, x - 25 * s * f, shoulder_y + 30 * s)
    elif pose == "walking":
        _limb(draw, x, shoulder_y, x + 38 * s * f, shoulder_y - 10 * s)
        _limb(draw, x, shoulder_y, x - 32 * s * f, shoulder_y + 30 * s)
    elif pose == "kneeling":
        _limb(draw, x, shoulder_y, x + 20 * s * f, shoulder_y + 25 * s)
        _limb(draw, x, shoulder_y, x - 20 * s * f, shoulder_y + 25 * s)
    else:
        _limb(draw, x, shoulder_y, x + 28 * s * f, shoulder_y + 35 * s)
        _limb(draw, x, shoulder_y, x - 28 * s * f, shoulder_y + 35 * s)

    if prop:
        _draw_prop(draw, prop, x, y, hip_y, s, f)


def _draw_temple(draw, cx, base_y, width, height, color=(225, 220, 210)):
    col_count = 5
    col_w = width / (col_count * 2.2)
    spacing = width / (col_count - 1)
    left = cx - width / 2

    draw.rectangle([left, base_y - height * 0.08, left + width, base_y], fill=color, outline=FIGURE_COLOR, width=3)
    for i in range(col_count):
        cx_i = left + i * spacing
        draw.rectangle([cx_i - col_w / 2, base_y - height, cx_i + col_w / 2, base_y - height * 0.08],
                        fill=color, outline=FIGURE_COLOR, width=3)
    draw.polygon(
        [(left - 15, base_y - height), (cx, base_y - height * 1.35), (left + width + 15, base_y - height)],
        fill=color, outline=FIGURE_COLOR,
    )


def _draw_hills(draw, width, base_y, color=(190, 175, 130)):
    draw.ellipse([-100, base_y - 60, width * 0.5, base_y + 200], fill=color)
    draw.ellipse([width * 0.35, base_y - 90, width * 1.1, base_y + 200], fill=color)


def _draw_ship(draw, cx, base_y, width, color=(120, 85, 55)):
    """Larger hull + taller mast/sail, and the mast is offset from center so a
    centered figure standing on deck doesn't visually block it."""
    draw.polygon(
        [(cx - width / 2, base_y), (cx + width / 2, base_y), (cx + width * 0.4, base_y + 55), (cx - width * 0.4, base_y + 55)],
        fill=color, outline=FIGURE_COLOR, width=3,
    )
    mast_x = cx - width * 0.28  # offset left of center, away from a centered figure
    draw.line([mast_x, base_y, mast_x, base_y - 220], fill=(80, 60, 40), width=10)
    draw.polygon(
        [(mast_x, base_y - 220), (mast_x, base_y - 30), (mast_x + 110, base_y - 90)],
        fill=(235, 230, 215), outline=FIGURE_COLOR, width=3,
    )


def _draw_wall(draw, width, base_y, height=90, color=(180, 165, 145)):
    draw.rectangle([0, base_y - height, width, base_y], fill=color, outline=FIGURE_COLOR, width=3)
    for x in range(0, int(width), 60):
        draw.rectangle([x, base_y - height, x + 40, base_y - height + 20], fill=(160, 145, 125))


LANDMARKS = {"temple": _draw_temple, "hills": _draw_hills, "ship": _draw_ship, "wall": _draw_wall}


def draw_scene(width: int, height: int, sky: str, landmark: str, figures: list[dict]) -> Image.Image:
    """
    Composition tuned for 9:16 vertical video: scene occupies the lower ~55% of the
    frame, keeping the top third clear for title/text overlay as requested.
    """
    sky_color = BG_SKY_COLORS.get(sky, BG_SKY_COLORS["plain"])
    img = Image.new("RGB", (width, height), sky_color)
    draw = ImageDraw.Draw(img)

    ground_y = int(height * 0.82)

    if landmark == "temple":
        _draw_temple(draw, width * 0.5, ground_y, width * 0.85, height * 0.32)
    elif landmark == "hills":
        _draw_hills(draw, width, ground_y)
    elif landmark == "ship":
        _draw_ship(draw, width * 0.5, ground_y, width * 0.7)
    elif landmark == "wall":
        _draw_wall(draw, width, ground_y)

    draw.line([0, ground_y, width, ground_y], fill=(60, 50, 35), width=5)

    for fig in figures:
        draw_pose(
            draw, fig["pose"], fig["x"], fig["y"],
            fig.get("scale", 1.0), fig.get("facing", 1),
            fig.get("robe_color", "white"), fig.get("prop"),
        )

    return img
