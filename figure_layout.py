def position_figures(figure_specs: list[dict], width: int, height: int, has_landmark: bool) -> list[dict]:
    """
    Takes 1-3 figure specs, each {"pose", "robe_color", "prop"}, and returns fully-
    positioned figures with x/y/scale/facing computed. Figures are laid out left to
    right in the order given, with left-side figures facing right (+1) and right-side
    figures facing left (-1) - toward each other - so multi-figure scenes read as a
    genuine interaction (a trial, an arrest, a conversation) rather than unrelated
    people who happen to share a frame.
    """
    n = len(figure_specs)
    figure_y = int(height * 0.68)

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
