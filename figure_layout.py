# Must match stick_figures.py draw_scene()'s ground_y exactly, and draw_pose()'s
# per-pose hip offsets exactly - both duplicated here deliberately (importing
# stick_figures here would create a circular import, since stick_figures never
# needs to import figure_layout at module level either).
_GROUND_Y_FRACTION = 0.82
_HIP_OFFSET_KNEELING = 70
_HIP_OFFSET_STANDING = 100


def position_figures(figure_specs: list[dict], width: int, height: int, has_landmark: bool) -> list[dict]:
    """
    Takes 1-3 figure specs, each {"pose", "robe_color", "prop"}, and returns fully-
    positioned figures with x/y/scale/facing computed. Figures are laid out left to
    right in the order given, with left-side figures facing right (+1) and right-side
    figures facing left (-1) - toward each other - so multi-figure scenes read as a
    genuine interaction (a trial, an arrest, a conversation) rather than unrelated
    people who happen to share a frame.

    Each figure's y (neck/shoulder position) is computed BACKWARD from the ground
    line, per-figure, based on that figure's own pose and scale - not a fixed
    constant. The previous fixed-neck-height approach caused feet to visibly float
    above the ground by anywhere from ~10px up to ~130px depending on figure count
    and scale, since the neck-to-hip distance scales with figure size while the old
    fixed neck position did not - the smaller the scale (more figures, or a
    landmark present), the bigger the visible gap became. Computing backward from
    the ground guarantees every figure's feet land exactly on the ground line
    regardless of scale or pose.
    """
    n = len(figure_specs)
    ground_y = int(height * _GROUND_Y_FRACTION)

    if n == 1:
        slots = [(0.5, 1)]
        scale = 2.2 if has_landmark else 2.6
    elif n == 2:
        slots = [(0.34, 1), (0.66, -1)]
        scale = 1.7 if has_landmark else 2.0
    else:  # 3
        slots = [(0.20, 1), (0.5, 1), (0.80, -1)]
        scale = 1.35 if has_landmark else 1.55

    positioned = []
    for spec, (x_frac, default_facing) in zip(figure_specs, slots):
        hip_offset = _HIP_OFFSET_KNEELING if spec["pose"] == "kneeling" else _HIP_OFFSET_STANDING
        figure_y = ground_y - int(hip_offset * scale)
        positioned.append({
            "pose": spec["pose"],
            "robe_color": spec["robe_color"],
            "prop": spec.get("prop"),
            "x": int(width * x_frac),
            "y": figure_y,
            "scale": scale,
            "facing": default_facing,
        })
    return positioned
