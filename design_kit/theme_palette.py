"""Graphite / cyan palette dicts — **reference copy** inside `design_kit/`.

This file in `design_kit/` is **not** meant to be uploaded or shipped with your
app repo. Copy (or merge) this file into your **project root** next to your main
GUI module as `theme_palette.py`, and load it from there at runtime.

Your app should hold ``self._pal: dict[str, str]`` and swap PALETTE_DARK /
PALETTE_LIGHT when the user toggles appearance (see `example_app.py` in this
folder for the pattern).
"""

PALETTE_DARK = {
    "bg": "#0c0c12",
    "panel": "#14141c",
    "panel_elev": "#1a1a26",
    "border": "#2a2a3a",
    "text": "#f0f0f8",
    "muted": "#7a7a92",
    "cyan": "#00c8ff",
    "cyan_dim": "#006080",
    "cyan_hover": "#33d6ff",
    "gold": "#c9a227",
    "gold_dim": "#6b5a12",
    "stop": "#e53935",
    "btn_rim": "#050508",
    "primary_border": "#021a22",
}

PALETTE_LIGHT = {
    "bg": "#e4e9f2",
    "panel": "#f5f7fb",
    "panel_elev": "#ffffff",
    "border": "#b4bccf",
    "text": "#10141c",
    "muted": "#4a5568",
    "cyan": "#007ea3",
    "cyan_dim": "#0096c7",
    "cyan_hover": "#23b2e0",
    "gold": "#a67c00",
    "gold_dim": "#c9a227",
    "stop": "#c62828",
    "btn_rim": "#1e2430",
    "primary_border": "#005a75",
}
