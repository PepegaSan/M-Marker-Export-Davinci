#!/usr/bin/env python3
"""GUI: DaVinci Resolve Deliver batch (main) + optional ffmpeg split (fallback)."""
from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any, Literal

import customtkinter as ctk

import davinci_api as dvr
from chapters import Chapter, chapters_from_edl, chapters_from_fcpxml, export_with_ffmpeg
from resolve_export import list_render_presets_sync, run_resolve_deliver
from theme_palette import PALETTE_DARK, PALETTE_LIGHT

ROOT = Path(__file__).resolve().parent
SETTINGS_PATH = ROOT / "user_settings.json"


def _load_user_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.is_file():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_user_settings(data: dict[str, Any]) -> None:
    SETTINGS_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _apply_resolve_overrides_from_disk(d: dict[str, Any]) -> None:
    dvr.set_resolve_install_overrides(
        resolve_exe=(d.get("resolve_exe") or "").strip() or None,
        scripting_modules_dir=(d.get("resolve_modules_dir") or "").strip() or None,
        fusionscript_dll=(d.get("resolve_fusionscript_dll") or "").strip() or None,
    )

BTN_RADIUS = 10
BTN_H = 36
FONT_UI = ("Segoe UI", 14)
FONT_HINT = ("Segoe UI", 11)
FONT_SECTION = ("Segoe UI Semibold", 15)

HELP_RESOLVE = """Resolve Studio — Help

Deliver
• DaVinci Resolve Studio with a project open; uses the **active timeline**.
• One Deliver job per chapter (MarkIn / MarkOut in **record frames**).

Range source
• **Timeline** — Chapters from markers: **Timeline ruler** or **Source / clip** (see checkboxes). **Between markers only** (default on): *N* markers → *N−1* clips `[M_i, M_{i+1})` — no extra export starting at the last marker. Optional: extend last segment (only when “between markers” is off), minutes cap, zero-duration filter.
• **FCPXML / EDL** — Ranges come entirely from the chosen file (set FPS). No “extend last”, no minutes cap, no zero-duration filter (timeline-only options).

Workflow
• If the edit is already in Resolve and you use timeline markers, **Timeline** is usually enough. Use **FCPXML / EDL** only when ranges must be read from a file on disk.

Between markers (timeline only)
• **On** (default): e.g. three markers → **two** clips (marker 1→2 and 2→3). **No** third clip from marker 3 to the end.
• **Off**: each marker starts a chapter; the last chapter follows **Extend last segment** and marker duration.

Extend last segment (timeline only; disabled when “between markers” is on)
• **On**: last chapter runs to timeline/clip end; cap length with **Last marker max (min)** (empty = 15 min default, 0 = unlimited).
• **Off**: last chapter ends at the marker (set marker duration in Resolve; plain **M** with no duration ≈ 1 frame).

Zero-duration markers (timeline only)
• Otherwise markers with no / very short duration are skipped.

Render preset
• Name must match Resolve → Deliver exactly. Save defaults in **⚙ Settings**; **Load presets** fills the list from the project.
"""

HELP_FFMPEG = """ffmpeg fallback — Help

• Without DaVinci Resolve: split one media file using FCPXML or EDL (`ffmpeg`, often `-c copy`).
• FPS and timecodes in the sidecar must match the chosen media file.
• **Overwrite existing clips**: replaces output files with the same name.
"""


class AutocutApp(ctk.CTk):
    def __init__(self) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        super().__init__(fg_color=PALETTE_DARK["bg"])
        self._pal: dict[str, str] = dict(PALETTE_DARK)
        self._appearance = ctk.StringVar(value="dark")

        # Resolve (main)
        self.range_source_var = tk.StringVar(value="timeline")
        self.sidecar_resolve_var = tk.StringVar()
        self.fps_resolve_var = tk.StringVar(value="25")
        self.out_resolve_var = tk.StringVar(value=str(ROOT / "exports" / "resolve_clips"))
        self._user_settings = _load_user_settings()
        _apply_resolve_overrides_from_disk(self._user_settings)
        _saved_preset = (self._user_settings.get("render_preset") or "").strip()
        self.preset_var = tk.StringVar(value=_saved_preset or "YouTube - 1080p")
        self.base_name_var = tk.StringVar(value="chapter")
        _tms = (self._user_settings.get("timeline_marker_scope") or "timeline").strip().lower()
        if _tms == "source_clip":
            self._marker_use_timeline_ruler = tk.BooleanVar(value=False)
            self._marker_use_source_clip = tk.BooleanVar(value=True)
        else:
            self._marker_use_timeline_ruler = tk.BooleanVar(value=True)
            self._marker_use_source_clip = tk.BooleanVar(value=False)
        self.zero_duration_var = tk.BooleanVar(value=False)
        # If last timeline marker has no "next marker", cap its length (minutes).
        # Minutes: empty = default 15 min cap for last marker; "0" = unlimited (full clip).
        self.last_marker_cap_min_var = tk.StringVar(value="")
        # If True (default), last chapter runs to timeline/clip end (respecting minutes cap).
        self.extend_last_marker_segment_var = tk.BooleanVar(value=True)
        # True: N timeline markers → N−1 clips [M_i, M_{i+1}); last marker is only an end cut.
        _bm_default = self._user_settings.get("between_markers_only")
        if _bm_default is None:
            _bm_default = True
        self.between_markers_only_var = tk.BooleanVar(value=bool(_bm_default))

        # ffmpeg fallback
        self.sidecar_ff_var = tk.StringVar()
        self.source_ff_var = tk.StringVar(value="fcpxml")
        self.media_var = tk.StringVar()
        self.fps_ff_var = tk.StringVar(value="25")
        self.out_ff_var = tk.StringVar(value=str(ROOT / "exports" / "ffmpeg_clips"))
        self.overwrite_var = tk.BooleanVar(value=False)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self._worker: threading.Thread | None = None

        self.title("M Marker Export — DaVinci Resolve")
        self.geometry("920x760")
        self.minsize(800, 640)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build()
        self._apply_palette()
        self._update_resolve_rows()
        self.after(120, self._drain_log)

    def _build(self) -> None:
        top = ctk.CTkFrame(self, corner_radius=0, height=52)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(1, weight=1)
        self._lbl_title = ctk.CTkLabel(
            top,
            text="M Marker Export — Resolve Studio (main) · ffmpeg (fallback)",
            font=("Segoe UI Semibold", 15),
            fg_color="transparent",
        )
        self._lbl_title.grid(row=0, column=0, padx=14, pady=12, sticky="w")
        self._lbl_status = ctk.CTkLabel(top, text="Ready", font=FONT_UI, fg_color="transparent")
        self._lbl_status.grid(row=0, column=1, padx=8, pady=12, sticky="w")
        p0 = self._pal
        self._btn_settings = ctk.CTkButton(
            top,
            text="⚙",
            width=40,
            height=36,
            corner_radius=10,
            command=self._open_settings,
            font=("Segoe UI Semibold", 16),
            fg_color=p0["panel_elev"],
            hover_color=p0["border"],
            text_color=p0["text"],
            border_width=1,
            border_color=p0["border"],
        )
        self._btn_settings.grid(row=0, column=2, padx=(8, 4), pady=8, sticky="e")
        self._seg_appearance = ctk.CTkSegmentedButton(
            top,
            values=["dark", "light"],
            variable=self._appearance,
            command=lambda _v: self._on_appearance(),
            font=("Segoe UI", 12),
        )
        self._seg_appearance.grid(row=0, column=3, padx=(4, 12), pady=8, sticky="e")

        body = ctk.CTkFrame(self, corner_radius=10, border_width=1)
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 6))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self._tabs = ctk.CTkTabview(body)
        self._tabs.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        tr = self._tabs.add("Resolve Studio")
        tr.grid_columnconfigure(0, weight=1)
        tr.grid_rowconfigure(0, weight=1)
        sr = ctk.CTkScrollableFrame(tr, fg_color="transparent", corner_radius=0)
        sr.grid(row=0, column=0, sticky="nsew")
        sr.grid_columnconfigure(1, weight=1)

        r = 0
        row_resolve_head = ctk.CTkFrame(sr, fg_color="transparent")
        row_resolve_head.grid(row=r, column=0, columnspan=3, sticky="ew", padx=10, pady=(8, 4))
        row_resolve_head.grid_columnconfigure(0, weight=1)
        ptab = self._pal
        self._lbl_resolve_tagline = ctk.CTkLabel(
            row_resolve_head,
            text="Open Resolve Studio, active timeline — one Deliver export per chapter.",
            font=FONT_HINT,
            fg_color="transparent",
            anchor="w",
            text_color=ptab["muted"],
        )
        self._lbl_resolve_tagline.grid(row=0, column=0, sticky="w")
        self._btn_resolve_help = ctk.CTkButton(
            row_resolve_head,
            text="(i)",
            width=36,
            height=32,
            corner_radius=8,
            command=lambda: self._show_help("Resolve — Help", HELP_RESOLVE),
            font=("Segoe UI Semibold", 12),
            fg_color=ptab["panel_elev"],
            hover_color=ptab["border"],
            text_color=ptab["text"],
            border_width=1,
            border_color=ptab["border"],
        )
        self._btn_resolve_help.grid(row=0, column=1, padx=(10, 0), sticky="e")
        r += 1

        self._lbl_range = ctk.CTkLabel(sr, text="Range source", font=FONT_UI, fg_color="transparent")
        self._lbl_range.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._seg_range = ctk.CTkSegmentedButton(
            sr,
            values=["timeline", "fcpxml", "edl"],
            variable=self.range_source_var,
            command=lambda _v: self._update_resolve_rows(),
            font=("Segoe UI", 12),
        )
        self._seg_range.grid(row=r, column=1, columnspan=2, sticky="ew", padx=10, pady=6)
        r += 1

        self._lbl_marker_scope = ctk.CTkLabel(
            sr,
            text="Marker source (Timeline range only)",
            font=FONT_UI,
            fg_color="transparent",
        )
        self._lbl_marker_scope.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._frm_marker_scope = ctk.CTkFrame(sr, fg_color="transparent")
        self._frm_marker_scope.grid(row=r, column=1, columnspan=2, sticky="w", padx=10, pady=6)
        self._chk_marker_timeline = ctk.CTkCheckBox(
            self._frm_marker_scope,
            text="Timeline ruler",
            variable=self._marker_use_timeline_ruler,
            font=FONT_UI,
            command=self._on_marker_scope_timeline,
        )
        self._chk_marker_timeline.pack(side="left", padx=(0, 16))
        self._chk_marker_source = ctk.CTkCheckBox(
            self._frm_marker_scope,
            text="Source / clip (pool + timeline item) — playhead / V1",
            variable=self._marker_use_source_clip,
            font=FONT_UI,
            command=self._on_marker_scope_source,
        )
        self._chk_marker_source.pack(side="left")
        r += 1

        self._lbl_sc_r = ctk.CTkLabel(sr, text="FCPXML / EDL file", font=FONT_UI, fg_color="transparent")
        self._lbl_sc_r.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._ent_sc_r = ctk.CTkEntry(
            sr,
            textvariable=self.sidecar_resolve_var,
            placeholder_text="Only when source is FCPXML or EDL",
            font=FONT_UI,
        )
        self._ent_sc_r.grid(row=r, column=1, sticky="ew", padx=10, pady=6)
        self._btn_sc_r = ctk.CTkButton(sr, text="Browse", width=88, command=self._browse_sidecar_resolve)
        self._btn_sc_r.grid(row=r, column=2, padx=10, pady=6)
        r += 1

        self._lbl_fps_r = ctk.CTkLabel(sr, text="FPS (FCPXML/EDL only)", font=FONT_UI, fg_color="transparent")
        self._lbl_fps_r.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._ent_fps_r = ctk.CTkEntry(sr, textvariable=self.fps_resolve_var, width=140, font=FONT_UI)
        self._ent_fps_r.grid(row=r, column=1, sticky="w", padx=10, pady=6)
        r += 1

        self._lbl_out_r = ctk.CTkLabel(sr, text="Output folder (Deliver)", font=FONT_UI, fg_color="transparent")
        self._lbl_out_r.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._ent_out_r = ctk.CTkEntry(sr, textvariable=self.out_resolve_var, font=FONT_UI)
        self._ent_out_r.grid(row=r, column=1, sticky="ew", padx=10, pady=6)
        self._btn_out_r = ctk.CTkButton(sr, text="Browse", width=88, command=self._browse_out_resolve)
        self._btn_out_r.grid(row=r, column=2, padx=10, pady=6)
        r += 1

        self._lbl_preset = ctk.CTkLabel(sr, text="Render preset", font=FONT_UI, fg_color="transparent")
        self._lbl_preset.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._combo_preset = ctk.CTkComboBox(
            sr,
            variable=self.preset_var,
            values=["YouTube - 1080p", "H.264 Master"],
            state="normal",
            font=FONT_UI,
        )
        self._combo_preset.grid(row=r, column=1, sticky="ew", padx=10, pady=6)
        self._btn_presets = ctk.CTkButton(sr, text="Load presets", width=110, command=self._load_presets)
        self._btn_presets.grid(row=r, column=2, padx=10, pady=6)
        r += 1
        _preset_defaults = ["YouTube - 1080p", "H.264 Master"]
        _cur_preset = self.preset_var.get().strip()
        if _cur_preset and _cur_preset not in _preset_defaults:
            self._combo_preset.configure(values=[_cur_preset, *_preset_defaults])
        else:
            self._combo_preset.configure(values=_preset_defaults)

        self._lbl_base = ctk.CTkLabel(sr, text="Output base name", font=FONT_UI, fg_color="transparent")
        self._lbl_base.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._ent_base = ctk.CTkEntry(sr, textvariable=self.base_name_var, font=FONT_UI)
        self._ent_base.grid(row=r, column=1, columnspan=2, sticky="ew", padx=10, pady=6)
        r += 1

        row_z = ctk.CTkFrame(sr, fg_color="transparent")
        row_z.grid(row=r, column=1, columnspan=2, sticky="w", padx=10, pady=(4, 8))
        self._chk_zero = ctk.CTkCheckBox(
            row_z,
            text="Include zero-duration markers (1 frame)",
            variable=self.zero_duration_var,
            font=FONT_UI,
        )
        self._chk_zero.pack(side="left")
        r += 1

        self._chk_between = ctk.CTkCheckBox(
            sr,
            text="Between markers only (no clip from last marker onward)",
            variable=self.between_markers_only_var,
            font=FONT_UI,
            command=self._on_between_markers_toggle,
        )
        self._chk_between.grid(row=r, column=0, columnspan=3, sticky="w", padx=10, pady=(2, 4))
        r += 1

        self._chk_extend_last = ctk.CTkCheckBox(
            sr,
            text="Extend last marker segment to timeline / clip end",
            variable=self.extend_last_marker_segment_var,
            font=FONT_UI,
            command=self._on_extend_last_toggle,
        )
        self._chk_extend_last.grid(row=r, column=0, columnspan=3, sticky="w", padx=10, pady=(2, 8))
        r += 1

        self._lbl_last_cap = ctk.CTkLabel(
            sr,
            text="Last marker max (min)",
            font=FONT_UI,
            fg_color="transparent",
        )
        self._lbl_last_cap.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._ent_last_cap = ctk.CTkEntry(
            sr,
            textvariable=self.last_marker_cap_min_var,
            placeholder_text="empty = 15 min cap | 0 = full clip | e.g. 45",
            font=FONT_UI,
        )
        self._ent_last_cap.grid(row=r, column=1, columnspan=2, sticky="ew", padx=10, pady=6)
        r += 1
        self._on_extend_last_toggle()

        self._btn_resolve = ctk.CTkButton(
            sr,
            text="Run Deliver (Resolve)",
            width=200,
            height=BTN_H,
            command=self._run_resolve,
        )
        self._btn_resolve.grid(row=r, column=0, columnspan=3, padx=10, pady=12, sticky="w")

        tf = self._tabs.add("ffmpeg (fallback)")
        tf.grid_columnconfigure(0, weight=1)
        tf.grid_rowconfigure(0, weight=1)
        sf = ctk.CTkScrollableFrame(tf, fg_color="transparent", corner_radius=0)
        sf.grid(row=0, column=0, sticky="nsew")
        sf.grid_columnconfigure(1, weight=1)

        r = 0
        row_ff_head = ctk.CTkFrame(sf, fg_color="transparent")
        row_ff_head.grid(row=r, column=0, columnspan=3, sticky="ew", padx=10, pady=(8, 4))
        row_ff_head.grid_columnconfigure(0, weight=1)
        self._lbl_ff_tagline = ctk.CTkLabel(
            row_ff_head,
            text="Without Resolve: ffmpeg split from FCPXML / EDL.",
            font=FONT_HINT,
            fg_color="transparent",
            anchor="w",
            text_color=self._pal["muted"],
        )
        self._lbl_ff_tagline.grid(row=0, column=0, sticky="w")
        self._btn_ffmpeg_help = ctk.CTkButton(
            row_ff_head,
            text="(i)",
            width=36,
            height=32,
            corner_radius=8,
            command=lambda: self._show_help("ffmpeg — Help", HELP_FFMPEG),
            font=("Segoe UI Semibold", 12),
            fg_color=self._pal["panel_elev"],
            hover_color=self._pal["border"],
            text_color=self._pal["text"],
            border_width=1,
            border_color=self._pal["border"],
        )
        self._btn_ffmpeg_help.grid(row=0, column=1, padx=(10, 0), sticky="e")
        r += 1

        self._lbl_sff = ctk.CTkLabel(sf, text="Sidecar type", font=FONT_UI, fg_color="transparent")
        self._lbl_sff.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._seg_ff = ctk.CTkSegmentedButton(
            sf,
            values=["fcpxml", "edl"],
            variable=self.source_ff_var,
            font=("Segoe UI", 12),
        )
        self._seg_ff.grid(row=r, column=1, columnspan=2, sticky="ew", padx=10, pady=6)
        r += 1

        self._lbl_scf = ctk.CTkLabel(sf, text="FCPXML / EDL file", font=FONT_UI, fg_color="transparent")
        self._lbl_scf.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._ent_scf = ctk.CTkEntry(sf, textvariable=self.sidecar_ff_var, font=FONT_UI)
        self._ent_scf.grid(row=r, column=1, sticky="ew", padx=10, pady=6)
        self._btn_scf = ctk.CTkButton(sf, text="Browse", width=88, command=self._browse_sidecar_ff)
        self._btn_scf.grid(row=r, column=2, padx=10, pady=6)
        r += 1

        self._lbl_mf = ctk.CTkLabel(sf, text="Media file", font=FONT_UI, fg_color="transparent")
        self._lbl_mf.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._ent_mf = ctk.CTkEntry(sf, textvariable=self.media_var, font=FONT_UI)
        self._ent_mf.grid(row=r, column=1, sticky="ew", padx=10, pady=6)
        self._btn_mf = ctk.CTkButton(sf, text="Browse", width=88, command=self._browse_media)
        self._btn_mf.grid(row=r, column=2, padx=10, pady=6)
        r += 1

        self._lbl_fpsf = ctk.CTkLabel(sf, text="FPS", font=FONT_UI, fg_color="transparent")
        self._lbl_fpsf.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._ent_fpsf = ctk.CTkEntry(sf, textvariable=self.fps_ff_var, width=120, font=FONT_UI)
        self._ent_fpsf.grid(row=r, column=1, sticky="w", padx=10, pady=6)
        r += 1

        self._lbl_outf = ctk.CTkLabel(sf, text="Output folder", font=FONT_UI, fg_color="transparent")
        self._lbl_outf.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._ent_outf = ctk.CTkEntry(sf, textvariable=self.out_ff_var, font=FONT_UI)
        self._ent_outf.grid(row=r, column=1, columnspan=2, sticky="ew", padx=10, pady=6)
        r += 1

        row_ff = ctk.CTkFrame(sf, fg_color="transparent")
        row_ff.grid(row=r, column=1, columnspan=2, sticky="w", padx=10, pady=(4, 8))
        self._chk_ow = ctk.CTkCheckBox(
            row_ff,
            text="Overwrite existing clips",
            variable=self.overwrite_var,
            font=FONT_UI,
        )
        self._chk_ow.pack(side="left")
        r += 1

        self._btn_ffmpeg = ctk.CTkButton(
            sf,
            text="Run ffmpeg split",
            width=180,
            height=BTN_H,
            command=self._run_ffmpeg,
        )
        self._btn_ffmpeg.grid(row=r, column=0, columnspan=3, padx=10, pady=12, sticky="w")

        log_host = ctk.CTkFrame(self, corner_radius=10, border_width=1)
        log_host.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 8))
        log_host.grid_rowconfigure(1, weight=1)
        log_host.grid_columnconfigure(0, weight=1)
        self._progress = ctk.CTkProgressBar(log_host)
        self._progress.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 4))
        self._progress.set(0)
        self._log = ctk.CTkTextbox(log_host, wrap="word", font=("Consolas", 12))
        self._log.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self._log.insert("end", "Resolve tab: markers on the active timeline, or ranges from FCPXML/EDL.\n")
        self._log.configure(state="disabled")
        self.grid_rowconfigure(2, weight=1)

    def _show_help(self, title: str, body: str) -> None:
        p = self._pal
        win = ctk.CTkToplevel(self)
        win.title(title)
        win.geometry("600x520")
        win.minsize(420, 300)
        win.transient(self)
        win.configure(fg_color=p["bg"])
        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            win,
            text=title,
            font=FONT_SECTION,
            fg_color="transparent",
            text_color=p["text"],
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 8))
        box = ctk.CTkTextbox(
            win,
            wrap="word",
            font=("Segoe UI", 13),
            fg_color=p["panel_elev"],
            border_color=p["border"],
            text_color=p["text"],
        )
        box.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 10))
        box.insert("1.0", body.strip())
        box.configure(state="disabled")
        ctk.CTkButton(
            win,
            text="Close",
            width=120,
            height=36,
            command=win.destroy,
            fg_color=p["cyan_dim"],
            hover_color=p["cyan"],
            text_color=p["text"],
            border_width=2,
            border_color=p.get("primary_border", p["border"]),
            font=("Segoe UI Semibold", 12),
        ).grid(row=2, column=0, pady=(0, 16))
        def _lift_focus() -> None:
            win.lift()
            win.focus_force()

        win.after(80, _lift_focus)

    def _open_settings(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        p = self._pal
        win = ctk.CTkToplevel(self)
        win.title("Settings")
        win.geometry("700x460")
        win.minsize(560, 400)
        win.transient(self)
        win.configure(fg_color=p["bg"])
        win.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            win,
            text="Saved to user_settings.json next to the app (see user_settings.example.json).",
            font=FONT_HINT,
            text_color=p["muted"],
            fg_color="transparent",
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(12, 4))

        sv_preset = tk.StringVar(value=self.preset_var.get())
        sv_mod = tk.StringVar(value=str(self._user_settings.get("resolve_modules_dir") or ""))
        sv_dll = tk.StringVar(value=str(self._user_settings.get("resolve_fusionscript_dll") or ""))
        sv_exe = tk.StringVar(value=str(self._user_settings.get("resolve_exe") or ""))

        def add_row(
            r: int,
            title: str,
            hint: str,
            var: tk.StringVar,
            browse_cmd=None,
        ) -> int:
            ctk.CTkLabel(win, text=title, font=FONT_UI, text_color=p["text"], fg_color="transparent").grid(
                row=r, column=0, sticky="nw", padx=14, pady=(8, 0)
            )
            ctk.CTkLabel(win, text=hint, font=FONT_HINT, text_color=p["muted"], fg_color="transparent").grid(
                row=r + 1, column=0, sticky="w", padx=14, pady=(0, 2)
            )
            e = ctk.CTkEntry(
                win,
                textvariable=var,
                font=FONT_UI,
                fg_color=p["panel_elev"],
                border_color=p["border"],
                text_color=p["text"],
            )
            if browse_cmd is not None:
                e.grid(row=r, column=1, rowspan=2, sticky="ew", padx=(0, 6), pady=4)
                ctk.CTkButton(win, text="…", width=36, command=browse_cmd, **self._button_kw("ghost")).grid(
                    row=r, column=2, rowspan=2, padx=(0, 14), pady=4
                )
            else:
                e.grid(row=r, column=1, columnspan=2, rowspan=2, sticky="ew", padx=(0, 14), pady=4)
            return r + 2

        r = 1
        r = add_row(
            r,
            "Render preset (Deliver)",
            "Exact name as in Resolve; empty = use combo default.",
            sv_preset,
        )

        def browse_mod() -> None:
            d = filedialog.askdirectory(title="Scripting Modules folder (contains DaVinciResolveScript.py)")
            if d:
                sv_mod.set(d)

        def browse_dll() -> None:
            f = filedialog.askopenfilename(
                title="fusionscript.dll",
                filetypes=[("DLL", "*.dll"), ("All", "*.*")],
            )
            if f:
                sv_dll.set(f)

        def browse_exe() -> None:
            f = filedialog.askopenfilename(
                title="Resolve.exe",
                filetypes=[("Executable", "*.exe"), ("All", "*.*")],
            )
            if f:
                sv_exe.set(f)

        r = add_row(
            r,
            "Resolve scripting API (Modules folder)",
            r"Optional: …\Support\Developer\Scripting\Modules (or parent Scripting folder).",
            sv_mod,
            browse_mod,
        )
        r = add_row(
            r,
            "fusionscript.dll",
            "Optional: full path to the DLL of the Resolve install you want.",
            sv_dll,
            browse_dll,
        )
        r = add_row(
            r,
            "Resolve.exe",
            "Optional: if Resolve is not in the default install location.",
            sv_exe,
            browse_exe,
        )

        def save_settings() -> None:
            pre = sv_preset.get().strip()
            mod = sv_mod.get().strip()
            dll = sv_dll.get().strip()
            exe = sv_exe.get().strip()
            if mod and not dvr.scripting_modules_dir_is_valid(mod):
                messagebox.showerror(
                    "Settings",
                    "Invalid scripting Modules path (DaVinciResolveScript.py not found).",
                )
                return
            if dll and not Path(dll).is_file():
                messagebox.showerror("Settings", "fusionscript.dll not found.")
                return
            if exe and not Path(exe).is_file():
                messagebox.showerror("Settings", "Resolve.exe not found.")
                return
            new: dict[str, Any] = {**self._user_settings}
            new["render_preset"] = pre
            new["resolve_modules_dir"] = mod
            new["resolve_fusionscript_dll"] = dll
            new["resolve_exe"] = exe
            _save_user_settings(new)
            self._user_settings = new
            _apply_resolve_overrides_from_disk(new)
            defaults = ["YouTube - 1080p", "H.264 Master"]
            self.preset_var.set(pre if pre else defaults[0])
            curp = self.preset_var.get().strip()
            if curp and curp not in defaults:
                self._combo_preset.configure(values=[curp, *defaults])
            else:
                self._combo_preset.configure(values=defaults)
            messagebox.showinfo("Settings", "Saved. The next Resolve run will use these paths.")
            win.destroy()

        row_btns = r
        ctk.CTkButton(
            win,
            text="Save",
            width=120,
            command=save_settings,
            **self._button_kw("primary"),
        ).grid(row=row_btns, column=1, sticky="e", padx=8, pady=(18, 14))
        ctk.CTkButton(
            win,
            text="Cancel",
            width=100,
            command=win.destroy,
            **self._button_kw("ghost"),
        ).grid(row=row_btns, column=2, sticky="w", padx=8, pady=(18, 14))

        def _lift() -> None:
            win.lift()
            win.focus_force()

        win.after(60, _lift)

    def _on_marker_scope_timeline(self) -> None:
        """Mutually exclusive with source-clip checkbox (timeline mode)."""
        if self._marker_use_timeline_ruler.get():
            self._marker_use_source_clip.set(False)
        elif not self._marker_use_source_clip.get():
            self._marker_use_timeline_ruler.set(True)

    def _on_marker_scope_source(self) -> None:
        if self._marker_use_source_clip.get():
            self._marker_use_timeline_ruler.set(False)
        elif not self._marker_use_timeline_ruler.get():
            self._marker_use_source_clip.set(True)

    def _timeline_marker_scope_setting(self) -> Literal["timeline", "source_clip"]:
        return "source_clip" if self._marker_use_source_clip.get() else "timeline"

    def _persist_timeline_marker_scope(self) -> None:
        d = dict(self._user_settings)
        d["timeline_marker_scope"] = self._timeline_marker_scope_setting()
        d["between_markers_only"] = bool(self.between_markers_only_var.get())
        _save_user_settings(d)
        self._user_settings = d

    def _on_between_markers_toggle(self) -> None:
        self._update_resolve_rows()

    def _on_extend_last_toggle(self) -> None:
        """Enable/disable minutes cap (only used when extending last segment)."""
        if self.range_source_var.get() != "timeline":
            return
        if self.between_markers_only_var.get():
            self._ent_last_cap.configure(state="disabled")
            self._lbl_last_cap.configure(text_color=self._pal["muted"])
            return
        extend = self.extend_last_marker_segment_var.get()
        if extend:
            self._ent_last_cap.configure(state="normal")
            self._lbl_last_cap.configure(text_color=self._pal["text"])
        else:
            self._ent_last_cap.configure(state="disabled")
            self._lbl_last_cap.configure(text_color=self._pal["muted"])

    def _update_resolve_rows(self) -> None:
        src = self.range_source_var.get()
        need_sidecar = src in ("fcpxml", "edl")
        st = "normal" if need_sidecar else "disabled"
        self._ent_sc_r.configure(state=st)
        self._btn_sc_r.configure(state=st)
        self._ent_fps_r.configure(state=st)
        self._lbl_sc_r.configure(text_color=self._pal["text"] if need_sidecar else self._pal["muted"])
        self._lbl_fps_r.configure(text_color=self._pal["text"] if need_sidecar else self._pal["muted"])

        # Timeline-only: marker heuristics (extend last, minutes cap, zero-duration filter).
        if src == "timeline":
            self._chk_between.configure(state="normal")
            self._chk_zero.configure(state="normal")
            if self.between_markers_only_var.get():
                self._chk_extend_last.configure(state="disabled")
                self._ent_last_cap.configure(state="disabled")
                self._lbl_last_cap.configure(text_color=self._pal["muted"])
            else:
                self._chk_extend_last.configure(state="normal")
                self._on_extend_last_toggle()
        else:
            self._chk_between.configure(state="disabled")
            self._chk_extend_last.configure(state="disabled")
            self._ent_last_cap.configure(state="disabled")
            self._lbl_last_cap.configure(text_color=self._pal["muted"])
            self._chk_zero.configure(state="disabled")

        mst = "normal" if src == "timeline" else "disabled"
        self._chk_marker_timeline.configure(state=mst)
        self._chk_marker_source.configure(state=mst)
        self._lbl_marker_scope.configure(
            text_color=self._pal["text"] if src == "timeline" else self._pal["muted"]
        )

    def _browse_sidecar_resolve(self) -> None:
        p = filedialog.askopenfilename(
            title="FCPXML or EDL",
            filetypes=[("Sidecar", "*.fcpxml *.xml *.edl"), ("All", "*.*")],
        )
        if p:
            self.sidecar_resolve_var.set(p)
            low = p.lower()
            if low.endswith(".edl"):
                self.range_source_var.set("edl")
            elif low.endswith(".fcpxml") or low.endswith(".xml"):
                self.range_source_var.set("fcpxml")
            self._update_resolve_rows()

    def _browse_out_resolve(self) -> None:
        p = filedialog.askdirectory(title="Deliver output folder")
        if p:
            self.out_resolve_var.set(p)

    def _browse_sidecar_ff(self) -> None:
        p = filedialog.askopenfilename(
            title="FCPXML or EDL",
            filetypes=[("Sidecar", "*.fcpxml *.xml *.edl"), ("All", "*.*")],
        )
        if p:
            self.sidecar_ff_var.set(p)

    def _browse_media(self) -> None:
        p = filedialog.askopenfilename(
            title="Media file",
            filetypes=[("Media", "*.mp4 *.mov *.mkv *.mxf *.wav *.aac"), ("All", "*.*")],
        )
        if p:
            self.media_var.set(p)

    def _append_log(self, text: str) -> None:
        self._log.configure(state="normal")
        self._log.insert("end", text)
        self._log.see("end")
        self._log.configure(state="disabled")

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
        p = self._pal
        self.configure(fg_color=p["bg"])
        self._lbl_title.configure(text_color=p["text"])
        self._lbl_status.configure(text_color=p["muted"])
        self._seg_appearance.configure(
            fg_color=p["panel"],
            selected_color=p["cyan_dim"],
            selected_hover_color=p["cyan"],
            unselected_color=p["panel_elev"],
            unselected_hover_color=p["border"],
            text_color=p["text"],
        )
        for w in (self._lbl_resolve_tagline, self._lbl_ff_tagline):
            w.configure(text_color=p["muted"])
        for w in (
            self._lbl_range,
            self._lbl_marker_scope,
            self._lbl_sc_r,
            self._lbl_fps_r,
            self._lbl_out_r,
            self._lbl_preset,
            self._lbl_base,
            self._lbl_last_cap,
            self._lbl_sff,
            self._lbl_scf,
            self._lbl_mf,
            self._lbl_fpsf,
            self._lbl_outf,
        ):
            w.configure(text_color=p["text"])
        self._seg_range.configure(
            fg_color=p["panel"],
            selected_color=p["cyan_dim"],
            selected_hover_color=p["cyan"],
            unselected_color=p["panel_elev"],
            unselected_hover_color=p["border"],
            text_color=p["text"],
        )
        self._seg_ff.configure(
            fg_color=p["panel"],
            selected_color=p["cyan_dim"],
            selected_hover_color=p["cyan"],
            unselected_color=p["panel_elev"],
            unselected_hover_color=p["border"],
            text_color=p["text"],
        )
        for e in (
            self._ent_sc_r,
            self._ent_fps_r,
            self._ent_out_r,
            self._ent_base,
            self._ent_last_cap,
            self._ent_scf,
            self._ent_mf,
            self._ent_fpsf,
            self._ent_outf,
        ):
            e.configure(fg_color=p["panel"], border_color=p["border"], text_color=p["text"])
        self._combo_preset.configure(
            fg_color=p["panel"],
            border_color=p["border"],
            button_color=p["panel_elev"],
            button_hover_color=p["border"],
            text_color=p["text"],
        )
        for b in (
            self._btn_sc_r,
            self._btn_out_r,
            self._btn_presets,
            self._btn_scf,
            self._btn_mf,
        ):
            b.configure(**self._button_kw("ghost"))
        self._btn_resolve.configure(**self._button_kw("primary"))
        self._btn_ffmpeg.configure(**self._button_kw("primary"))
        self._chk_zero.configure(text_color=p["text"])
        self._chk_between.configure(text_color=p["text"])
        self._chk_extend_last.configure(text_color=p["text"])
        self._chk_marker_timeline.configure(text_color=p["text"])
        self._chk_marker_source.configure(text_color=p["text"])
        self._chk_ow.configure(text_color=p["text"])
        for hb in (self._btn_settings, self._btn_resolve_help, self._btn_ffmpeg_help):
            hb.configure(
                fg_color=p["panel_elev"],
                hover_color=p["border"],
                text_color=p["text"],
                border_color=p["border"],
            )
        self._progress.configure(progress_color=p["cyan"], fg_color=p["panel_elev"])
        self._log.configure(fg_color=p["panel_elev"], border_color=p["border"], text_color=p["text"])
        self._update_resolve_rows()
        self._on_extend_last_toggle()

    def _button_kw(self, variant: str) -> dict:
        p = self._pal
        base = dict(corner_radius=BTN_RADIUS, height=BTN_H, border_width=2, border_color=p["btn_rim"])
        if variant == "primary":
            base.update(
                fg_color=p["cyan_dim"],
                hover_color=p["cyan"],
                text_color=p["text"],
                border_color=p["primary_border"],
                font=("Segoe UI Black", 11),
            )
        else:
            base.update(
                fg_color=p["panel_elev"],
                hover_color=p["border"],
                text_color=p["text"],
                font=("Segoe UI Semibold", 10),
            )
        return base

    def _parse_progress(self, line: str) -> None:
        if "[progress]" in line and "/" in line:
            try:
                part = line.split("|", 1)[0]
                part = part.replace("[progress]", "").strip()
                a, b = part.split("/", 1)
                done, total = int(a), int(max(int(b), 1))
                self._progress.set(done / total)
                self._lbl_status.configure(text=f"{done}/{total}")
            except (ValueError, IndexError):
                pass

    def _set_busy(self, busy: bool) -> None:
        st = "disabled" if busy else "normal"
        self._btn_resolve.configure(state=st)
        self._btn_ffmpeg.configure(state=st)
        self._btn_presets.configure(state=st)
        self._btn_settings.configure(state=st)

    def _drain_log(self) -> None:
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(line)
            self._parse_progress(line)
        if self._worker is not None and not self._worker.is_alive():
            self._worker = None
            self._set_busy(False)
            if self._lbl_status.cget("text") != "Error":
                self._lbl_status.configure(text="Ready")
        self.after(120, self._drain_log)

    def _load_presets(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._btn_presets.configure(state="disabled")

        def work() -> None:
            try:
                names = list_render_presets_sync(
                    status_callback=lambda m: self.log_queue.put(f"[resolve] {m}\n"),
                )

                def apply_() -> None:
                    if names:
                        cur = self.preset_var.get().strip()
                        merged = list(dict.fromkeys(([cur] if cur else []) + list(names)))
                        self._combo_preset.configure(values=merged)
                        self.preset_var.set(cur if cur else names[0])
                        self.log_queue.put(f"[gui] Loaded {len(names)} preset(s).\n")
                    else:
                        self.log_queue.put("[gui] No presets returned.\n")
                    self._btn_presets.configure(state="normal")

                self.after(0, apply_)
            except Exception as exc:
                self.log_queue.put(f"[gui] Load presets failed: {exc}\n")
                self.after(0, lambda: self._btn_presets.configure(state="normal"))

        threading.Thread(target=work, daemon=True).start()

    def _run_resolve(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        src = self.range_source_var.get()
        sidecar: Path | None = None
        fps_o: float | None = None
        if src in ("fcpxml", "edl"):
            p = self.sidecar_resolve_var.get().strip()
            if not p or not Path(p).is_file():
                messagebox.showerror("Sidecar", "Choose a valid FCPXML or EDL file.")
                return
            sidecar = Path(p)
            try:
                fps_o = float((self.fps_resolve_var.get() or "25").replace(",", "."))
                if fps_o <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("FPS", "Enter a positive FPS.")
                return
        try:
            out_dir = Path(self.out_resolve_var.get().strip() or str(ROOT / "exports" / "resolve_clips"))
        except Exception:
            messagebox.showerror("Output", "Invalid output folder.")
            return

        preset = self.preset_var.get().strip() or None
        base = self.base_name_var.get().strip() or "chapter"

        extend_last = self.extend_last_marker_segment_var.get()
        last_marker_max_sec: float | None
        if extend_last:
            raw_cap = (self.last_marker_cap_min_var.get() or "").strip().replace(",", ".")
            if raw_cap == "":
                last_marker_max_sec = 15.0 * 60.0
            elif raw_cap in ("0", "0.0", "none", "None", "off", "OFF"):
                last_marker_max_sec = None
            else:
                try:
                    m = float(raw_cap)
                    if m < 0:
                        raise ValueError
                    last_marker_max_sec = m * 60.0
                except ValueError:
                    messagebox.showerror(
                        "Last marker cap",
                        "Use a non-negative number (minutes), empty = 15 min default, 0 = unlimited.",
                    )
                    return
        else:
            last_marker_max_sec = None

        self._set_busy(True)
        self._lbl_status.configure(text="Resolve…")
        self._progress.set(0)
        self._append_log("\n--- Resolve Deliver ---\n")
        if src == "timeline":
            self._persist_timeline_marker_scope()

        def work() -> None:
            try:
                run_resolve_deliver(
                    range_source=src,
                    sidecar_path=sidecar,
                    fps_override=fps_o,
                    out_dir=out_dir,
                    base_name=base,
                    preset_name=preset,
                    include_zero_duration=self.zero_duration_var.get(),
                    last_marker_max_sec=last_marker_max_sec,
                    extend_last_marker_segment=extend_last,
                    between_markers_only=self.between_markers_only_var.get(),
                    timeline_marker_scope=self._timeline_marker_scope_setting(),
                    status_callback=lambda m: self.log_queue.put(m),
                )
                self.log_queue.put(f"Done. Output: {out_dir}\n")
            except Exception as exc:
                self.log_queue.put(f"ERROR: {exc}\n")
                self.after(0, lambda: self._lbl_status.configure(text="Error"))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _run_ffmpeg(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        sidecar = self.sidecar_ff_var.get().strip()
        media = self.media_var.get().strip()
        if not sidecar or not Path(sidecar).is_file():
            messagebox.showerror("Sidecar", "Choose a valid FCPXML or EDL file.")
            return
        if not media or not Path(media).is_file():
            messagebox.showerror("Media", "Choose a valid media file.")
            return
        try:
            fps = float((self.fps_ff_var.get() or "25").replace(",", "."))
            if fps <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("FPS", "Enter a positive FPS.")
            return

        out_dir = Path(self.out_ff_var.get().strip() or str(ROOT / "exports" / "ffmpeg_clips"))
        src: Literal["fcpxml", "edl"] = "edl" if self.source_ff_var.get() == "edl" else "fcpxml"

        self._set_busy(True)
        self._lbl_status.configure(text="ffmpeg…")
        self._progress.set(0)
        self._append_log("\n--- ffmpeg ---\n")

        def work() -> None:
            try:
                path = Path(sidecar)
                media_path = Path(media)
                if src == "fcpxml":
                    chapters: list[Chapter] = chapters_from_fcpxml(path, fps)
                else:
                    chapters = chapters_from_edl(path, fps)
                self.log_queue.put(f"Parsed {len(chapters)} segment(s).\n")
                export_with_ffmpeg(
                    media_path,
                    chapters,
                    fps,
                    out_dir,
                    overwrite=self.overwrite_var.get(),
                    log=lambda s: self.log_queue.put(s),
                )
                self.log_queue.put(f"Done. Output: {out_dir}\n")
            except Exception as exc:
                self.log_queue.put(f"ERROR: {exc}\n")
                self.after(0, lambda: self._lbl_status.configure(text="Error"))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()


def main() -> None:
    AutocutApp().mainloop()


if __name__ == "__main__":
    main()
