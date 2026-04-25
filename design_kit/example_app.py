#!/usr/bin/env python3
"""Minimal CustomTkinter shell using the shared dark/light palette layout.

The ``design_kit/`` folder is **reference only** (not shipped with slim repos).
For a real app, copy ``theme_palette.py`` into the **project root** and wire
``self._pal`` there; use this file only as a runnable demo / snippet source.

Run from this folder:
    pip install customtkinter
    python example_app.py

Copy ``theme_palette.py`` (to the target project root) and optionally ideas
from this file into another project and adapt panel content. For cards /
Enter-to-submit / batch-safety ideas, read ``WORKFLOW_UI_PATTERNS.md`` in this
folder.

-------------------------------------------------------------------------------
IMPORTANT — THEME SWITCHING PATTERN
-------------------------------------------------------------------------------
CustomTkinter does NOT automatically repaint widgets when you change the
appearance mode. Every widget that uses a palette colour (``fg_color``,
``text_color``, ``border_color``, ``hover_color`` on buttons, the palette-
driven colours on ``CTkSegmentedButton`` etc.) must be:

    1. created with a colour sourced from ``self._pal``, and
    2. stored as an instance attribute (``self._foo = ctk.CTk...``), and
    3. re-configured inside ``_apply_palette()`` so it picks up the new values.

Skipping any of these three steps leaves orphan dark widgets in light mode
(and vice versa). Treat ``_apply_palette()`` as the *only* place that maps
palette keys to widgets — nowhere else in the app should read
``PALETTE_DARK`` / ``PALETTE_LIGHT`` directly.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import customtkinter as ctk

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from theme_palette import PALETTE_DARK, PALETTE_LIGHT  # noqa: E402

BTN_RADIUS = 10
BTN_H = 36
FONT_APP_TITLE = ("Segoe UI Black", 18)
FONT_UI = ("Segoe UI", 14)
FONT_UI_SM = ("Segoe UI", 12)
FONT_HINT = ("Segoe UI", 11)
FONT_SECTION = ("Segoe UI Semibold", 15)
FONT_BTN = ("Segoe UI Black", 10)
FONT_BTN_PRIMARY = ("Segoe UI Black", 11)
FONT_BTN_NAV = ("Segoe UI Semibold", 10)


class DemoApp(ctk.CTk):
    def __init__(self) -> None:
        ctk.set_default_color_theme("blue")
        ctk.set_appearance_mode("dark")
        super().__init__(fg_color=PALETTE_DARK["bg"])
        self._pal: dict[str, str] = dict(PALETTE_DARK)
        self._appearance = ctk.StringVar(value="dark")

        self.title("Design kit — example shell")
        self.geometry("900x620")
        self.minsize(640, 480)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Toggle-row state (see _build_toggle_demo / _toggle_advanced).
        # ``_simple_switch`` drives the single on/off demo; the advanced
        # demo combines a switch + expand button + parameter entries to
        # show the "sub-options collapsible" pattern from main.py's EQ
        # row. StringVars rather than DoubleVars so the user can have
        # an empty / mid-edit field without Tk binding errors.
        self._simple_switch = ctk.BooleanVar(value=True)
        self._adv_switch = ctk.BooleanVar(value=True)
        self._adv_freq = ctk.StringVar(value="145")
        self._adv_gain = ctk.StringVar(value="3.5")
        self._adv_expanded = False

        self._build()
        self._apply_palette()  # single source of truth for colours

    def _build_workflow_cards_demo(self, parent: ctk.CTkFrame) -> None:
        """Elevated cards + Enter-bound search (see WORKFLOW_UI_PATTERNS.md)."""
        p = self._pal
        parent.grid_columnconfigure(0, weight=1)

        self._demo_card_a = ctk.CTkFrame(
            parent,
            corner_radius=10,
            border_width=1,
            fg_color=p["panel_elev"],
            border_color=p["border"],
        )
        self._demo_card_a.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self._demo_card_a.grid_columnconfigure(1, weight=1)

        self._demo_card_title_a = ctk.CTkLabel(
            self._demo_card_a,
            text="Card — search block",
            font=FONT_SECTION,
            fg_color="transparent",
        )
        self._demo_card_title_a.grid(row=0, column=0, columnspan=3, sticky="w", padx=10, pady=(8, 4))

        self._demo_search_entry = ctk.CTkEntry(
            self._demo_card_a,
            placeholder_text="Type a query, then press Enter…",
            font=FONT_UI,
        )
        self._demo_search_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=6)
        self._demo_search_entry.bind("<Return>", self._on_demo_search_return)

        self._demo_search_btn = ctk.CTkButton(
            self._demo_card_a,
            text="Search",
            width=100,
            command=self._demo_fake_search,
            **self._button_kw("ghost"),
        )
        self._demo_search_btn.grid(row=1, column=2, padx=8, pady=6, sticky="e")

        self._demo_search_hint = ctk.CTkLabel(
            self._demo_card_a,
            text="Press Enter in the field to run the same handler as the Search button.",
            font=FONT_HINT,
            fg_color="transparent",
            justify="left",
            anchor="w",
            wraplength=560,
        )
        self._demo_search_hint.grid(row=2, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 8))

        self._demo_card_b = ctk.CTkFrame(
            parent,
            corner_radius=10,
            border_width=1,
            fg_color=p["panel_elev"],
            border_color=p["border"],
        )
        self._demo_card_b.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        self._demo_card_b.grid_columnconfigure(1, weight=1)

        self._demo_card_title_b = ctk.CTkLabel(
            self._demo_card_b,
            text="Card — results / status strip",
            font=FONT_SECTION,
            fg_color="transparent",
        )
        self._demo_card_title_b.grid(row=0, column=0, columnspan=3, sticky="w", padx=10, pady=(8, 4))

        row = ctk.CTkFrame(self._demo_card_b, fg_color="transparent")
        row.grid(row=1, column=0, columnspan=3, sticky="ew", padx=8, pady=(0, 8))
        row.grid_columnconfigure(1, weight=1)

        self._demo_results_count = ctk.CTkLabel(
            row,
            text="Matches: —",
            font=FONT_UI,
            fg_color="transparent",
            anchor="w",
        )
        self._demo_results_count.grid(row=0, column=0, sticky="w", padx=2)

        self._demo_empty_hint = ctk.CTkLabel(
            row,
            text="Empty-state hint appears here after you search (demo).",
            font=FONT_HINT,
            fg_color="transparent",
            anchor="w",
        )
        self._demo_empty_hint.grid(row=0, column=1, sticky="w", padx=12)

        self._demo_dirty_badge = ctk.CTkLabel(
            row,
            text="Unsaved",
            font=FONT_UI_SM,
            fg_color="transparent",
        )
        self._demo_dirty_badge.grid(row=0, column=2, sticky="e", padx=8)
        self._demo_dirty_badge.grid_remove()

    def _on_demo_search_return(self, _event: Any = None) -> str:
        self._demo_fake_search()
        return "break"

    def _demo_fake_search(self) -> None:
        q = self._demo_search_entry.get().strip() or "(empty query)"
        self._demo_results_count.configure(text=f"Matches: demo — «{q}»")
        self._demo_empty_hint.configure(text="")
        self._demo_dirty_badge.grid(row=0, column=2, sticky="e", padx=8)

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        """Create every widget once. Colours are finalised in ``_apply_palette``."""
        p = self._pal

        # Top bar -----------------------------------------------------------
        self._frame_top = ctk.CTkFrame(self, corner_radius=0, height=56)
        self._frame_top.grid(row=0, column=0, sticky="ew")
        self._frame_top.grid_columnconfigure(1, weight=1)

        self._lbl_title = ctk.CTkLabel(
            self._frame_top,
            text="Your app title",
            font=FONT_APP_TITLE,
            fg_color="transparent",
        )
        self._lbl_title.grid(row=0, column=0, padx=(18, 10), pady=12, sticky="w")

        self._lbl_status = ctk.CTkLabel(
            self._frame_top,
            text="Status or progress text",
            font=FONT_UI,
            fg_color="transparent",
        )
        self._lbl_status.grid(row=0, column=1, sticky="w", padx=6, pady=12)

        self._btn_primary = ctk.CTkButton(
            self._frame_top,
            text="Primary",
            width=120,
            command=lambda: None,
            **self._button_kw("primary_emphasis"),
        )
        self._btn_primary.grid(row=0, column=2, padx=(6, 14), pady=8, sticky="e")

        # Body --------------------------------------------------------------
        self._body = ctk.CTkFrame(self)
        self._body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(8, 10))
        self._body.grid_columnconfigure(1, weight=1)
        self._body.grid_rowconfigure(0, weight=1)

        self._side = ctk.CTkFrame(
            self._body, width=200, corner_radius=14, border_width=1
        )
        self._side.grid(row=0, column=0, sticky="ns", padx=(0, 10), pady=0)
        self._side.grid_propagate(False)

        self._btn_nav_active = ctk.CTkButton(
            self._side,
            text="Active nav (example)",
            **self._button_kw("nav_active", height=44),
        )
        self._btn_nav_active.pack(fill="x", padx=10, pady=(14, 6))

        self._btn_nav_idle = ctk.CTkButton(
            self._side,
            text="Idle nav (example)",
            **self._button_kw("nav_idle", height=44),
        )
        self._btn_nav_idle.pack(fill="x", padx=10, pady=4)

        self._content = ctk.CTkFrame(self._body, corner_radius=10, border_width=1)
        self._content.grid(row=0, column=1, sticky="nsew")
        self._content.grid_columnconfigure(0, weight=1)

        self._lbl_content = ctk.CTkLabel(
            self._content,
            text=(
                "Patterns below: (1) section cards + Enter-to-submit search, "
                "(2) results strip with empty-state hint + unsaved badge demo. "
                "Lower block: CTkSwitch patterns."
            ),
            font=FONT_UI,
            fg_color="transparent",
            anchor="w",
            justify="left",
            wraplength=640,
        )
        self._lbl_content.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))

        self._workflow_strip = ctk.CTkFrame(self._content, fg_color="transparent")
        self._workflow_strip.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        self._workflow_strip.grid_columnconfigure(0, weight=1)
        self._build_workflow_cards_demo(self._workflow_strip)

        self._toggle_host = ctk.CTkFrame(self._content, fg_color="transparent")
        self._toggle_host.grid(row=2, column=0, sticky="nsew", padx=4, pady=0)
        self._content.grid_rowconfigure(2, weight=1)
        self._toggle_host.grid_columnconfigure(0, weight=1)
        self._toggle_host.grid_rowconfigure(0, weight=1)
        self._build_toggle_demo(parent=self._toggle_host)

        # Bottom bar --------------------------------------------------------
        self._bar = ctk.CTkFrame(self, corner_radius=0, height=44)
        self._bar.grid(row=2, column=0, sticky="ew")

        self._seg = ctk.CTkSegmentedButton(
            self._bar,
            values=["dark", "light"],
            variable=self._appearance,
            command=lambda _v: self._on_appearance(),
            font=FONT_UI_SM,
        )
        self._seg.pack(side="left", padx=12, pady=6)

    # ------------------------------------------------------------ toggles
    def _build_toggle_demo(self, *, parent: ctk.CTkFrame) -> None:
        """Two reusable toggle patterns.

        1. **Simple switch row** — one ``CTkSwitch`` + a muted hint
           label under it. Use this when the option is a pure on/off
           with no follow-up parameters (checkbox with context).
        2. **Advanced switch row** — a ``CTkSwitch`` + an "Advanced ▾"
           button that expands/collapses a sub-frame with
           CTkEntry fields. The sub-frame is gridded in/out by
           ``_toggle_advanced`` so the main form stays compact when
           the defaults are good enough.

        Both rely on the standard ``self._pal`` colour dict and are
        re-themed inside ``_apply_palette()`` — see the bottom of that
        method.
        """
        p = self._pal

        # Simple switch pattern -------------------------------------
        self._simple_row = ctk.CTkFrame(parent, fg_color="transparent")
        self._simple_row.grid(row=0, column=0, sticky="ew", padx=16, pady=(6, 0))
        self._simple_row.grid_columnconfigure(0, weight=1)

        self._simple_switch_widget = ctk.CTkSwitch(
            self._simple_row,
            text="Enable feature X (simple on/off pattern)",
            variable=self._simple_switch,
            onvalue=True,
            offvalue=False,
            font=FONT_UI,
        )
        self._simple_switch_widget.grid(row=0, column=0, sticky="w")

        self._simple_hint = ctk.CTkLabel(
            self._simple_row,
            text=(
                "ON: the feature runs.  OFF: it is skipped. One line of "
                "muted hint text keeps the switch self-explanatory without "
                "a modal."
            ),
            font=FONT_HINT,
            fg_color="transparent",
            justify="left",
            anchor="w",
            wraplength=520,
        )
        self._simple_hint.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        # Advanced switch pattern (switch + foldable options) -------
        self._adv_row = ctk.CTkFrame(parent, fg_color="transparent")
        self._adv_row.grid(row=1, column=0, sticky="ew", padx=16, pady=(14, 0))
        self._adv_row.grid_columnconfigure(0, weight=1)

        # Header: switch + expand button on the same line.
        self._adv_header = ctk.CTkFrame(self._adv_row, fg_color="transparent")
        self._adv_header.grid(row=0, column=0, sticky="ew")
        self._adv_header.grid_columnconfigure(0, weight=1)

        self._adv_switch_widget = ctk.CTkSwitch(
            self._adv_header,
            text="Enable feature Y (foldable advanced options)",
            variable=self._adv_switch,
            onvalue=True,
            offvalue=False,
            font=FONT_UI,
        )
        self._adv_switch_widget.grid(row=0, column=0, sticky="w")

        self._adv_toggle_btn = ctk.CTkButton(
            self._adv_header,
            text="Advanced ▾",
            width=110,
            command=self._toggle_advanced,
            **self._button_kw("ghost"),
        )
        self._adv_toggle_btn.grid(row=0, column=1, sticky="e")

        self._adv_hint = ctk.CTkLabel(
            self._adv_row,
            text=(
                "Click Advanced ▾ to reveal parameter fields. Optimal "
                "ranges for this hypothetical filter: freq 100–150 Hz, "
                "gain +2 to +4 dB. Defaults hidden until the user "
                "actually needs to tune."
            ),
            font=FONT_HINT,
            fg_color="transparent",
            justify="left",
            anchor="w",
            wraplength=520,
        )
        self._adv_hint.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        # Foldable sub-frame. Created once, gridded in/out on demand.
        self._adv_options = ctk.CTkFrame(
            self._adv_row,
            corner_radius=8,
            border_width=1,
        )
        self._adv_options.grid_columnconfigure(1, weight=1)

        def _mk_numeric_row(
            row: int,
            label_text: str,
            var: ctk.StringVar,
            unit: str,
            tip: str,
        ) -> ctk.CTkEntry:
            lbl = ctk.CTkLabel(
                self._adv_options,
                text=label_text,
                font=FONT_UI,
                fg_color="transparent",
                anchor="w",
                width=110,
            )
            lbl.grid(
                row=row, column=0, sticky="w",
                padx=(12, 8), pady=(8 if row == 0 else 4, 4),
            )
            entry = ctk.CTkEntry(
                self._adv_options,
                textvariable=var,
                width=110,
                font=FONT_UI,
            )
            entry.grid(
                row=row, column=1, sticky="w",
                padx=0, pady=(8 if row == 0 else 4, 4),
            )
            unit_lbl = ctk.CTkLabel(
                self._adv_options,
                text=unit,
                font=FONT_UI_SM,
                fg_color="transparent",
                anchor="w",
            )
            unit_lbl.grid(row=row, column=2, sticky="w", padx=(6, 12))
            tip_lbl = ctk.CTkLabel(
                self._adv_options,
                text=tip,
                font=FONT_HINT,
                fg_color="transparent",
                justify="left",
                anchor="w",
            )
            tip_lbl.grid(row=row, column=3, sticky="w", padx=(12, 12))
            return entry

        self._adv_freq_entry = _mk_numeric_row(
            0, "Frequency", self._adv_freq, "Hz",
            "example: 100–150 Hz",
        )
        self._adv_gain_entry = _mk_numeric_row(
            1, "Gain", self._adv_gain, "dB",
            "example: +2 to +4 dB",
        )

    def _toggle_advanced(self) -> None:
        """Expand / collapse the Advanced sub-frame. The caret on the
        button flips so users see the fold direction at a glance."""
        self._adv_expanded = not self._adv_expanded
        if self._adv_expanded:
            self._adv_options.grid(
                row=2, column=0, sticky="ew", padx=0, pady=(8, 0)
            )
            self._adv_toggle_btn.configure(text="Advanced ▴")
        else:
            self._adv_options.grid_forget()
            self._adv_toggle_btn.configure(text="Advanced ▾")

    # ------------------------------------------------------------- palette
    def _on_appearance(self) -> None:
        mode = (self._appearance.get() or "dark").strip().lower()
        if mode == "light":
            self._pal = dict(PALETTE_LIGHT)
            ctk.set_appearance_mode("light")
        else:
            self._pal = dict(PALETTE_DARK)
            ctk.set_appearance_mode("dark")
        self._apply_palette()

    def _apply_palette(self) -> None:
        """Single source of truth: every themed widget is recoloured here.

        When you add a new palette-driven widget in ``_build``, also add its
        ``.configure(...)`` call in this method. This is the ONLY reliable
        way to keep dark/light parity in CustomTkinter.
        """
        p = self._pal

        # Root + frames.
        self.configure(fg_color=p["bg"])
        self._frame_top.configure(fg_color=p["panel"])
        self._body.configure(fg_color=p["bg"])
        self._side.configure(fg_color=p["panel"], border_color=p["border"])
        self._content.configure(fg_color=p["panel"], border_color=p["border"])
        self._bar.configure(fg_color=p["panel_elev"])

        # Workflow card demo (see WORKFLOW_UI_PATTERNS.md).
        self._demo_card_a.configure(fg_color=p["panel_elev"], border_color=p["border"])
        self._demo_card_b.configure(fg_color=p["panel_elev"], border_color=p["border"])
        self._demo_card_title_a.configure(text_color=p["text"])
        self._demo_card_title_b.configure(text_color=p["text"])
        self._demo_search_entry.configure(
            fg_color=p["panel"], border_color=p["border"], text_color=p["text"]
        )
        self._demo_search_btn.configure(**self._button_kw("ghost"))
        self._demo_search_hint.configure(text_color=p["muted"])
        self._demo_results_count.configure(text_color=p["text"])
        self._demo_empty_hint.configure(text_color=p["muted"])
        self._demo_dirty_badge.configure(text_color=p["gold"])

        # Labels.
        self._lbl_title.configure(text_color=p["text"])
        self._lbl_status.configure(text_color=p["muted"])
        self._lbl_content.configure(text_color=p["text"])

        # Buttons — re-apply the full variant kwargs so every hover / border
        # colour stays in sync with the palette.
        self._btn_primary.configure(**self._button_kw("primary_emphasis"))
        self._btn_nav_active.configure(**self._button_kw("nav_active", height=44))
        self._btn_nav_idle.configure(**self._button_kw("nav_idle", height=44))

        # Segmented control.
        self._seg.configure(
            fg_color=p["panel"],
            selected_color=p["cyan_dim"],
            selected_hover_color=p["cyan"],
            unselected_color=p["panel_elev"],
            unselected_hover_color=p["border"],
            text_color=p["text"],
        )

        # --- Toggle demo ---------------------------------------------
        # Switches: the ``progress_color`` is what the thumb lights up
        # in when the switch is ON — use the accent colour so the UI
        # reads at a glance. ``fg_color`` is the OFF track, ``button_*``
        # is the thumb itself in both states.
        switch_kw = dict(
            text_color=p["text"],
            progress_color=p["cyan"],
            button_color=p["panel"],
            button_hover_color=p["panel_elev"],
            fg_color=p["panel_elev"],
        )
        self._simple_switch_widget.configure(**switch_kw)
        self._adv_switch_widget.configure(**switch_kw)

        self._simple_hint.configure(text_color=p["muted"])
        self._adv_hint.configure(text_color=p["muted"])

        # Advanced-panel: the fold button is a ghost-variant; the panel
        # frame uses the elevated panel colour so it visually reads as a
        # nested card.
        self._adv_toggle_btn.configure(**self._button_kw("ghost"))
        self._adv_options.configure(
            fg_color=p["panel_elev"], border_color=p["border"]
        )
        for entry in (self._adv_freq_entry, self._adv_gain_entry):
            entry.configure(
                fg_color=p["panel"],
                border_color=p["border"],
                text_color=p["text"],
            )
        # Re-colour labels inside the options frame. Short labels +
        # units use the primary text colour, longer tip strings use
        # muted — same heuristic the main app uses.
        for child in self._adv_options.winfo_children():
            if isinstance(child, ctk.CTkLabel):
                text = str(child.cget("text") or "")
                child.configure(
                    text_color=p["text"] if len(text) < 16 else p["muted"]
                )

    # ------------------------------------------------------------- buttons
    def _button_kw(
        self,
        variant: str = "ghost",
        *,
        height: int = BTN_H,
        font: tuple | None = None,
        width: int | None = None,
    ) -> dict[str, Any]:
        """Central factory for ``CTkButton`` kwargs.

        Never pass any of the keys set here a second time at the call-site —
        CustomTkinter raises ``TypeError`` on duplicate keyword arguments.
        """
        p = self._pal
        kw: dict[str, Any] = dict(
            corner_radius=BTN_RADIUS,
            font=font or FONT_BTN,
            height=height,
            border_width=2,
            border_color=p["btn_rim"],
        )
        if width is not None:
            kw["width"] = width
        if variant == "ghost":
            kw.update(fg_color=p["panel_elev"], hover_color=p["border"], text_color=p["text"])
        elif variant == "primary":
            kw.update(
                fg_color=p["cyan_dim"],
                hover_color=p["cyan"],
                text_color=p["text"],
                border_color=p["primary_border"],
            )
        elif variant == "primary_emphasis":
            kw.update(
                fg_color=p["cyan_dim"],
                hover_color=p["cyan"],
                text_color=p["text"],
                border_color=p["primary_border"],
                font=FONT_BTN_PRIMARY,
            )
        elif variant == "nav_idle":
            kw.update(
                fg_color=p["panel_elev"],
                hover_color=p["border"],
                text_color=p["muted"],
                font=FONT_BTN_NAV,
            )
        elif variant == "nav_active":
            kw.update(
                fg_color=p["cyan_dim"],
                hover_color=p["cyan"],
                text_color=p["text"],
                border_color=p["cyan"],
                font=FONT_BTN,
            )
        return kw


def main() -> None:
    app = DemoApp()
    app.mainloop()


if __name__ == "__main__":
    main()
