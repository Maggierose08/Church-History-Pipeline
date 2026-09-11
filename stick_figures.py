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


SKIN_COLOR = (232, 194, 160)


HAIR_COLOR = (60, 42, 30)


def _draw_head(draw, cx, cy, r, facing=1):
    """Head circle, FILLED with a solid skin tone (previously just an unfilled
    outline, letting the background show through) plus simple facial features and
    hair. Eyes shift slightly toward `facing` direction so the figure visibly
    looks toward whoever/whatever it's facing, matching the interaction direction.
    Hair is deliberately gender-neutral in shape (a simple cap-like top rather
    than a style implying a specific gender) since the schema has no gender field
    - adding it safely for every figure without risking mismatched styling on
    female historical figures like Perpetua or Felicity.
    """
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=SKIN_COLOR, outline=FIGURE_COLOR, width=LINE_WIDTH)

    # Simple hair cap: an arc covering roughly the top half of the head.
    hair_bbox = [cx - r * 1.02, cy - r * 1.15, cx + r * 1.02, cy + r * 0.25]
    draw.pieslice(hair_bbox, start=180, end=360, fill=HAIR_COLOR, outline=FIGURE_COLOR, width=max(2, int(LINE_WIDTH * 0.5)))

    eye_offset_x = r * 0.28 * facing
    eye_y = cy - r * 0.12
    eye_r = max(2, r * 0.09)
    for side in (-1, 1):
        ex = cx + eye_offset_x + side * r * 0.32
        draw.ellipse([ex - eye_r, eye_y - eye_r, ex + eye_r, eye_y + eye_r], fill=FIGURE_COLOR)

    mouth_y = cy + r * 0.35
    mouth_half_w = r * 0.22
    mouth_x = cx + eye_offset_x * 0.5
    draw.line([mouth_x - mouth_half_w, mouth_y, mouth_x + mouth_half_w, mouth_y], fill=FIGURE_COLOR, width=max(2, int(LINE_WIDTH * 0.4)))


def _limb(draw, x1, y1, x2, y2, width=LINE_WIDTH):
    draw.line([x1, y1, x2, y2], fill=FIGURE_COLOR, width=width)


def _shade(rgb, factor):
    """Darkens (factor < 1) or lightens (factor > 1) an RGB color for fold shading."""
    return tuple(max(0, min(255, int(c * factor))) for c in rgb)


def _draw_robe(draw, x, y, hip_y, width_top, width_bottom, color):
    """
    Draws the robe as a trapezoid base, then adds a few subtle vertical fold lines
    plus a rounded hem - a flat single-color polygon reads as a plain block rather
    than fabric, so this adds simple shading/creases to break up that flat look
    without needing actual texture rendering.
    """
    rgb = ROBE_COLORS.get(color, ROBE_COLORS["white"])
    fold_dark = _shade(rgb, 0.82)
    fold_light = _shade(rgb, 1.12)

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

    # A rounded hem instead of a flat bottom edge - a small arc softens the "block" look.
    hem_height = (hip_y - y) * 0.06
    draw.ellipse(
        [x - width_bottom, hip_y - hem_height, x + width_bottom, hip_y + hem_height],
        fill=rgb, outline=FIGURE_COLOR,
    )

    # 3 subtle fold lines, alternating light/dark, fanning slightly outward toward the hem.
    fold_offsets = [-0.45, 0.0, 0.45]
    fold_colors = [fold_dark, fold_light, fold_dark]
    for offset, fold_color in zip(fold_offsets, fold_colors):
        top_x = x + offset * width_top * 0.7
        bottom_x = x + offset * width_bottom * 0.9
        draw.line([top_x, y + 4, bottom_x, hip_y - 4], fill=fold_color, width=3)

    # A simple belt/sash at the waist, on every figure - a small but real addition
    # of robe detail/style that doesn't depend on any gender-specific assumption.
    belt_y = y + (hip_y - y) * 0.42
    belt_half_width = width_top + (width_bottom - width_top) * 0.42
    draw.line([x - belt_half_width, belt_y, x + belt_half_width, belt_y], fill=fold_dark, width=6)

    # A hood, for robe colors that read as more monastic/humble (brown, a wandering
    # hermit or shepherd's cloak) or more formally religious (purple, a bishop's
    # vestment) - not tied to any figure gender, purely a robe-color-based style
    # choice, so it stays safe without a gender field in the schema.
    if color in ("brown", "purple"):
        # A rounded cowl shape sitting on the shoulders behind the head/neck,
        # wider than the robe collar - drawn as a simple ellipse rather than a
        # pieslice, which is easier to make read clearly as "hood fabric" rather
        # than stray side flaps.
        hood_w = width_top * 2.6
        hood_h = width_top * 2.0
        draw.ellipse(
            [x - hood_w / 2, y - hood_h * 0.35, x + hood_w / 2, y + hood_h * 0.65],
            fill=rgb, outline=FIGURE_COLOR, width=3,
        )


def _draw_prop(draw, prop, x, y, hip_y, scale, facing):
    s = scale
    f = facing
    if prop == "staff":
        top_x, top_y = x + 55 * s * f, y - 60 * s
        bot_x, bot_y = x + 45 * s * f, hip_y + 60 * s
        draw.line([top_x, top_y, bot_x, bot_y], fill=(90, 65, 40), width=int(LINE_WIDTH * 0.8))
    elif prop == "scroll":
        scroll_x0 = x + 20 * s * f
        scroll_x1 = x + 50 * s * f
        draw.rounded_rectangle(
            [min(scroll_x0, scroll_x1), y + 35 * s, max(scroll_x0, scroll_x1), y + 58 * s],
            radius=6, fill=(230, 218, 190), outline=FIGURE_COLOR, width=3,
        )
    elif prop == "cross":
        cx, cy = x - 55 * s * f, y - 20 * s
        draw.line([cx, cy - 30 * s, cx, cy + 30 * s], fill=(80, 60, 45), width=int(LINE_WIDTH * 0.8))
        draw.line([cx - 15 * s, cy - 12 * s, cx + 15 * s, cy - 12 * s], fill=(80, 60, 45), width=int(LINE_WIDTH * 0.8))
    elif prop == "book":
        book_x0 = min(x + 18 * s * f, x + 52 * s * f)
        book_x1 = max(x + 18 * s * f, x + 52 * s * f)
        draw.rectangle(
            [book_x0, y + 32 * s, book_x1, y + 62 * s],
            fill=(150, 60, 50), outline=FIGURE_COLOR, width=3,
        )
        draw.line([(book_x0 + book_x1) / 2, y + 32 * s, (book_x0 + book_x1) / 2, y + 62 * s], fill=FIGURE_COLOR, width=2)
    elif prop == "torch":
        top_x, top_y = x + 55 * s * f, y - 55 * s
        bot_x, bot_y = x + 48 * s * f, hip_y + 40 * s
        draw.line([top_x, top_y, bot_x, bot_y], fill=(90, 65, 40), width=int(LINE_WIDTH * 0.7))
        flame_pts = [
            (top_x, top_y - 35 * s), (top_x - 12 * s, top_y - 8 * s),
            (top_x, top_y + 5 * s), (top_x + 12 * s, top_y - 8 * s),
        ]
        draw.polygon(flame_pts, fill=(240, 140, 40), outline=(200, 90, 20))


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

    hip_y = y + (70 * s if pose == "kneeling" else 100 * s)

    _draw_robe(draw, x, y, hip_y, 22 * s, 55 * s, robe_color)

    if pose == "kneeling":
        _limb(draw, x - 12 * s * f, hip_y, x + 18 * s * f, hip_y + 6 * s, width=int(LINE_WIDTH * 0.7))
    elif pose == "sitting":
        _limb(draw, x, hip_y, x + 45 * s * f, hip_y, width=int(LINE_WIDTH * 0.8))
        _limb(draw, x + 45 * s * f, hip_y, x + 45 * s * f, hip_y + 50 * s, width=int(LINE_WIDTH * 0.8))
    elif pose == "walking":
        _limb(draw, x - 8 * s * f, hip_y, x + 32 * s * f, hip_y + 15 * s, width=int(LINE_WIDTH * 0.7))
        _limb(draw, x - 8 * s * f, hip_y, x - 25 * s * f, hip_y + 20 * s, width=int(LINE_WIDTH * 0.7))
    elif pose == "grieving":
        _limb(draw, x - 10 * s * f, hip_y, x + 6 * s * f, hip_y + 15 * s, width=int(LINE_WIDTH * 0.7))
        _limb(draw, x - 10 * s * f, hip_y, x - 16 * s * f, hip_y + 15 * s, width=int(LINE_WIDTH * 0.7))
    else:  # standing, writing, raising_arms
        _limb(draw, x - 10 * s * f, hip_y, x + 12 * s * f, hip_y + 15 * s, width=int(LINE_WIDTH * 0.7))
        _limb(draw, x - 10 * s * f, hip_y, x - 20 * s * f, hip_y + 15 * s, width=int(LINE_WIDTH * 0.7))

    _draw_head(draw, x, y - head_r - 4 * s, head_r, facing=f)

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
    elif pose == "writing":
        _limb(draw, x + 6 * s * f, shoulder_y, x + 45 * s * f, shoulder_y + 55 * s)
        _limb(draw, x, shoulder_y, x - 22 * s * f, shoulder_y + 30 * s)
    elif pose == "raising_arms":
        _limb(draw, x, shoulder_y, x + 75 * s * f, shoulder_y - 85 * s)
        _limb(draw, x, shoulder_y, x - 75 * s * f, shoulder_y - 85 * s)
    elif pose == "grieving":
        _limb(draw, x, shoulder_y, x + 14 * s * f, shoulder_y - 15 * s)
        _limb(draw, x, shoulder_y, x - 14 * s * f, shoulder_y - 15 * s)
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
    mast_x = cx - width * 0.28
    draw.line([mast_x, base_y, mast_x, base_y - 220], fill=(80, 60, 40), width=10)
    draw.polygon(
        [(mast_x, base_y - 220), (mast_x, base_y - 30), (mast_x + 110, base_y - 90)],
        fill=(235, 230, 215), outline=FIGURE_COLOR, width=3,
    )


def _draw_wall(draw, width, base_y, height=90, color=(180, 165, 145)):
    draw.rectangle([0, base_y - height, width, base_y], fill=color, outline=FIGURE_COLOR, width=3)
    for x in range(0, int(width), 60):
        draw.rectangle([x, base_y - height, x + 40, base_y - height + 20], fill=(160, 145, 125))


def _draw_prison(draw, width, base_y, color=(120, 115, 110)):
    """A simple stone building with barred windows - relevant background for the
    many captivity-themed scenes in this content (Perpetua's prison, Patrick's
    enslavement, Polycarp's farmhouse hideout)."""
    building_h = 260
    draw.rectangle([width * 0.15, base_y - building_h, width * 0.85, base_y], fill=color, outline=FIGURE_COLOR, width=3)
    bar_color = (60, 55, 50)
    window_y0, window_y1 = base_y - building_h * 0.72, base_y - building_h * 0.35
    for wx in [width * 0.28, width * 0.50, width * 0.72]:
        window_w = width * 0.12
        draw.rectangle([wx - window_w / 2, window_y0, wx + window_w / 2, window_y1], fill=(35, 32, 40), outline=FIGURE_COLOR, width=2)
        for bar_x_frac in [0.25, 0.5, 0.75]:
            bar_x = wx - window_w / 2 + window_w * bar_x_frac
            draw.line([bar_x, window_y0, bar_x, window_y1], fill=bar_color, width=4)


def _draw_arena(draw, width, base_y, color=(200, 180, 150)):
    """A Roman amphitheater interior - tiered stone seating rings around a sand
    floor - distinct from the temple's exterior columned facade. Relevant for
    the many martyrdom-in-the-arena climaxes in this content."""
    tier_colors = [(170, 155, 130), (185, 168, 142), (200, 180, 150)]
    for i, tier_color in enumerate(tier_colors):
        tier_top = base_y - 340 + i * 90
        inset = i * 90
        draw.polygon(
            [(inset, tier_top), (width - inset, tier_top), (width - inset * 0.6, base_y), (inset * 0.6, base_y)],
            fill=tier_color, outline=FIGURE_COLOR, width=2,
        )
    draw.rectangle([0, base_y - 20, width, base_y], fill=(210, 190, 150), outline=FIGURE_COLOR, width=2)


def _draw_road(draw, width, base_y, color=(175, 155, 125)):
    """A traveling/journey background - a dirt road receding into the distance
    with sparse trees, for the many travel/exile/journey scenes in this content
    (previously these had no landmark at all, just an empty sky)."""
    draw.polygon(
        [(width * 0.35, base_y - 250), (width * 0.65, base_y - 250), (width * 0.92, base_y), (width * 0.08, base_y)],
        fill=color, outline=FIGURE_COLOR, width=2,
    )
    for tx, th in [(width * 0.12, 70), (width * 0.85, 90), (width * 0.05, 55)]:
        draw.ellipse([tx - 22, base_y - 250 - th, tx + 22, base_y - 250 - th + 60], fill=(120, 140, 90))
        draw.line([tx, base_y - 250 - th + 40, tx, base_y - 250], fill=(90, 65, 40), width=6)


def _draw_courtroom(draw, width, base_y, color=(195, 185, 175)):
    """A formal hall interior - a raised judgment platform with a backdrop wall -
    distinct from a temple exterior or a plain wall, for trial/sentencing scenes."""
    draw.rectangle([0, base_y - 280, width, base_y], fill=color, outline=FIGURE_COLOR, width=3)
    draw.rectangle([width * 0.55, base_y - 60, width * 0.95, base_y], fill=(160, 148, 135), outline=FIGURE_COLOR, width=3)
    for px in range(0, int(width), 90):
        draw.line([px, base_y - 280, px, base_y], fill=(175, 165, 155), width=2)


LANDMARKS = {
    "temple": _draw_temple, "hills": _draw_hills, "ship": _draw_ship, "wall": _draw_wall,
    "prison": _draw_prison, "arena": _draw_arena, "road": _draw_road, "courtroom": _draw_courtroom,
}


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
        _draw_temple(draw, width * 0.18, ground_y, width * 0.28, height * 0.18, color=(200, 192, 200))
        _draw_temple(draw, width * 0.86, ground_y, width * 0.28, height * 0.18, color=(200, 192, 200))
        _draw_temple(draw, width * 0.5, ground_y, width * 0.85, height * 0.32)
    elif landmark == "hills":
        _draw_hills(draw, width, ground_y)
    elif landmark == "ship":
        _draw_ship(draw, width * 0.5, ground_y, width * 0.7)
    elif landmark == "wall":
        _draw_wall(draw, width, ground_y)
        for bx, bw, bh in [(width * 0.15, width * 0.12, 60), (width * 0.35, width * 0.10, 45),
                            (width * 0.62, width * 0.14, 70), (width * 0.82, width * 0.11, 50)]:
            draw.rectangle([bx, ground_y - 90 - bh, bx + bw, ground_y - 90], fill=(160, 150, 135), outline=FIGURE_COLOR, width=2)
    elif landmark == "prison":
        _draw_prison(draw, width, ground_y)
    elif landmark == "arena":
        _draw_arena(draw, width, ground_y)
    elif landmark == "road":
        _draw_road(draw, width, ground_y)
    elif landmark == "courtroom":
        _draw_courtroom(draw, width, ground_y)

    draw.line([0, ground_y, width, ground_y], fill=(60, 50, 35), width=5)

    for fig in figures:
        draw_pose(
            draw, fig["pose"], fig["x"], fig["y"],
            fig.get("scale", 1.0), fig.get("facing", 1),
            fig.get("robe_color", "white"), fig.get("prop"),
        )

    return img


def draw_crowd_silhouettes(draw, count: int, width: int, ground_y: int, scale: float = 0.9):
    """
    Draws `count` simplified, smaller background figures (no individual pose detail -
    just a simple robe-blob + head silhouette) scattered behind the main interacting
    figures, to suggest a larger crowd/mob/gathering without needing each person to
    be a fully articulated, individually-posed character.
    """
    import random
    rng = random.Random(count * 97 + width)
    silhouette_color = (90, 85, 95)
    for i in range(count):
        cx = width * (0.08 + 0.84 * i / max(1, count - 1)) + rng.uniform(-25, 25)
        head_r = 16 * scale
        body_h = 60 * scale
        cy = ground_y - body_h - head_r * 2 - rng.uniform(0, 15)
        draw.ellipse([cx - head_r, cy, cx + head_r, cy + head_r * 2], fill=silhouette_color)
        draw.polygon(
            [(cx - 14 * scale, cy + head_r * 2), (cx + 14 * scale, cy + head_r * 2),
             (cx + 22 * scale, cy + head_r * 2 + body_h), (cx - 22 * scale, cy + head_r * 2 + body_h)],
            fill=silhouette_color,
        )
