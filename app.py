#!/usr/bin/env python3
"""GUI: DaVinci Resolve Deliver batch (main) + optional ffmpeg split (fallback)."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Literal

import customtkinter as ctk

from chapters import Chapter, chapters_from_edl, chapters_from_fcpxml, export_with_ffmpeg
from resolve_export import list_render_presets_sync, run_resolve_deliver
from theme_palette import PALETTE_DARK, PALETTE_LIGHT

ROOT = Path(__file__).resolve().parent

BTN_RADIUS = 10
BTN_H = 36
FONT_UI = ("Segoe UI", 14)
FONT_HINT = ("Segoe UI", 11)
FONT_SECTION = ("Segoe UI Semibold", 15)


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
        self.preset_var = tk.StringVar(value="YouTube - 1080p")
        self.base_name_var = tk.StringVar(value="chapter")
        self.zero_duration_var = tk.BooleanVar(value=False)
        # If last timeline marker has no "next marker", cap its length (minutes).
        self.last_marker_cap_min_var = tk.StringVar(value="")

        # ffmpeg fallback
        self.sidecar_ff_var = tk.StringVar()
        self.source_ff_var = tk.StringVar(value="fcpxml")
        self.media_var = tk.StringVar()
        self.fps_ff_var = tk.StringVar(value="25")
        self.out_ff_var = tk.StringVar(value=str(ROOT / "exports" / "ffmpeg_clips"))
        self.overwrite_var = tk.BooleanVar(value=False)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self._worker: threading.Thread | None = None

        self.title("Marker autocut — Resolve Studio")
        self.geometry("920x700")
        self.minsize(800, 620)
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
            text="Marker autocut — Resolve Studio (main) · ffmpeg (fallback)",
            font=("Segoe UI Semibold", 15),
            fg_color="transparent",
        )
        self._lbl_title.grid(row=0, column=0, padx=14, pady=12, sticky="w")
        self._lbl_status = ctk.CTkLabel(top, text="Ready", font=FONT_UI, fg_color="transparent")
        self._lbl_status.grid(row=0, column=1, padx=8, pady=12, sticky="w")
        self._seg_appearance = ctk.CTkSegmentedButton(
            top,
            values=["dark", "light"],
            variable=self._appearance,
            command=lambda _v: self._on_appearance(),
            font=("Segoe UI", 12),
        )
        self._seg_appearance.grid(row=0, column=2, padx=12, pady=8, sticky="e")

        body = ctk.CTkFrame(self, corner_radius=10, border_width=1)
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 6))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self._tabs = ctk.CTkTabview(body)
        self._tabs.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        tr = self._tabs.add("Resolve Studio")
        tr.grid_columnconfigure(1, weight=1)
        r = 0
        self._tr_hint = ctk.CTkLabel(
            tr,
            text="Open your project and timeline in Resolve. Uses Deliver: one job per segment (MarkIn/MarkOut).",
            font=FONT_HINT,
            fg_color="transparent",
            anchor="w",
            wraplength=820,
        )
        self._tr_hint.grid(row=r, column=0, columnspan=3, sticky="ew", padx=10, pady=(8, 4))
        r += 1

        self._lbl_range = ctk.CTkLabel(tr, text="Range source", font=FONT_UI, fg_color="transparent")
        self._lbl_range.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._seg_range = ctk.CTkSegmentedButton(
            tr,
            values=["timeline", "fcpxml", "edl"],
            variable=self.range_source_var,
            command=lambda _v: self._update_resolve_rows(),
            font=("Segoe UI", 12),
        )
        self._seg_range.grid(row=r, column=1, columnspan=2, sticky="ew", padx=10, pady=6)
        r += 1

        self._lbl_sc_r = ctk.CTkLabel(tr, text="FCPXML / EDL file", font=FONT_UI, fg_color="transparent")
        self._lbl_sc_r.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._ent_sc_r = ctk.CTkEntry(
            tr,
            textvariable=self.sidecar_resolve_var,
            placeholder_text="Only when source is FCPXML or EDL",
            font=FONT_UI,
        )
        self._ent_sc_r.grid(row=r, column=1, sticky="ew", padx=10, pady=6)
        self._btn_sc_r = ctk.CTkButton(tr, text="Browse", width=88, command=self._browse_sidecar_resolve)
        self._btn_sc_r.grid(row=r, column=2, padx=10, pady=6)
        r += 1

        self._lbl_fps_r = ctk.CTkLabel(tr, text="FPS (FCPXML/EDL only)", font=FONT_UI, fg_color="transparent")
        self._lbl_fps_r.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._ent_fps_r = ctk.CTkEntry(tr, textvariable=self.fps_resolve_var, width=140, font=FONT_UI)
        self._ent_fps_r.grid(row=r, column=1, sticky="w", padx=10, pady=6)
        r += 1

        self._lbl_out_r = ctk.CTkLabel(tr, text="Output folder (Deliver)", font=FONT_UI, fg_color="transparent")
        self._lbl_out_r.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._ent_out_r = ctk.CTkEntry(tr, textvariable=self.out_resolve_var, font=FONT_UI)
        self._ent_out_r.grid(row=r, column=1, sticky="ew", padx=10, pady=6)
        self._btn_out_r = ctk.CTkButton(tr, text="Browse", width=88, command=self._browse_out_resolve)
        self._btn_out_r.grid(row=r, column=2, padx=10, pady=6)
        r += 1

        self._lbl_preset = ctk.CTkLabel(tr, text="Render preset", font=FONT_UI, fg_color="transparent")
        self._lbl_preset.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._combo_preset = ctk.CTkComboBox(
            tr,
            variable=self.preset_var,
            values=["YouTube - 1080p", "H.264 Master"],
            state="normal",
            font=FONT_UI,
        )
        self._combo_preset.grid(row=r, column=1, sticky="ew", padx=10, pady=6)
        self._btn_presets = ctk.CTkButton(tr, text="Load presets", width=110, command=self._load_presets)
        self._btn_presets.grid(row=r, column=2, padx=10, pady=6)
        r += 1

        self._lbl_base = ctk.CTkLabel(tr, text="Output base name", font=FONT_UI, fg_color="transparent")
        self._lbl_base.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._ent_base = ctk.CTkEntry(tr, textvariable=self.base_name_var, font=FONT_UI)
        self._ent_base.grid(row=r, column=1, columnspan=2, sticky="ew", padx=10, pady=6)
        r += 1

        row_z = ctk.CTkFrame(tr, fg_color="transparent")
        row_z.grid(row=r, column=1, columnspan=2, sticky="w", padx=10, pady=(4, 8))
        self._chk_zero = ctk.CTkCheckBox(
            row_z,
            text="Include zero-duration markers (1 frame)",
            variable=self.zero_duration_var,
            font=FONT_UI,
        )
        self._chk_zero.pack(side="left")
        r += 1

        self._lbl_last_cap = ctk.CTkLabel(
            tr,
            text="Last marker max length (min, optional)",
            font=FONT_UI,
            fg_color="transparent",
        )
        self._lbl_last_cap.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._ent_last_cap = ctk.CTkEntry(
            tr,
            textvariable=self.last_marker_cap_min_var,
            placeholder_text="e.g. 10 — empty = full clip/timeline end",
            font=FONT_UI,
        )
        self._ent_last_cap.grid(row=r, column=1, columnspan=2, sticky="ew", padx=10, pady=6)
        r += 1

        self._btn_resolve = ctk.CTkButton(
            tr,
            text="Run Deliver (Resolve)",
            width=200,
            height=BTN_H,
            command=self._run_resolve,
        )
        self._btn_resolve.grid(row=r, column=0, columnspan=3, padx=10, pady=12, sticky="w")

        tf = self._tabs.add("ffmpeg fallback")
        tf.grid_columnconfigure(1, weight=1)
        r = 0
        self._ff_hint = ctk.CTkLabel(
            tf,
            text="No Resolve: split one media file with ffmpeg (-c copy). Sidecar timebase must match your file.",
            font=FONT_HINT,
            fg_color="transparent",
            anchor="w",
            wraplength=820,
        )
        self._ff_hint.grid(row=r, column=0, columnspan=3, sticky="ew", padx=10, pady=(8, 4))
        r += 1

        self._lbl_sff = ctk.CTkLabel(tf, text="Sidecar type", font=FONT_UI, fg_color="transparent")
        self._lbl_sff.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._seg_ff = ctk.CTkSegmentedButton(
            tf,
            values=["fcpxml", "edl"],
            variable=self.source_ff_var,
            font=("Segoe UI", 12),
        )
        self._seg_ff.grid(row=r, column=1, columnspan=2, sticky="ew", padx=10, pady=6)
        r += 1

        self._lbl_scf = ctk.CTkLabel(tf, text="FCPXML / EDL file", font=FONT_UI, fg_color="transparent")
        self._lbl_scf.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._ent_scf = ctk.CTkEntry(tf, textvariable=self.sidecar_ff_var, font=FONT_UI)
        self._ent_scf.grid(row=r, column=1, sticky="ew", padx=10, pady=6)
        self._btn_scf = ctk.CTkButton(tf, text="Browse", width=88, command=self._browse_sidecar_ff)
        self._btn_scf.grid(row=r, column=2, padx=10, pady=6)
        r += 1

        self._lbl_mf = ctk.CTkLabel(tf, text="Media file", font=FONT_UI, fg_color="transparent")
        self._lbl_mf.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._ent_mf = ctk.CTkEntry(tf, textvariable=self.media_var, font=FONT_UI)
        self._ent_mf.grid(row=r, column=1, sticky="ew", padx=10, pady=6)
        self._btn_mf = ctk.CTkButton(tf, text="Browse", width=88, command=self._browse_media)
        self._btn_mf.grid(row=r, column=2, padx=10, pady=6)
        r += 1

        self._lbl_fpsf = ctk.CTkLabel(tf, text="FPS", font=FONT_UI, fg_color="transparent")
        self._lbl_fpsf.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._ent_fpsf = ctk.CTkEntry(tf, textvariable=self.fps_ff_var, width=120, font=FONT_UI)
        self._ent_fpsf.grid(row=r, column=1, sticky="w", padx=10, pady=6)
        r += 1

        self._lbl_outf = ctk.CTkLabel(tf, text="Output folder", font=FONT_UI, fg_color="transparent")
        self._lbl_outf.grid(row=r, column=0, sticky="w", padx=10, pady=6)
        self._ent_outf = ctk.CTkEntry(tf, textvariable=self.out_ff_var, font=FONT_UI)
        self._ent_outf.grid(row=r, column=1, columnspan=2, sticky="ew", padx=10, pady=6)
        r += 1

        row_ff = ctk.CTkFrame(tf, fg_color="transparent")
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
            tf,
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

    def _update_resolve_rows(self) -> None:
        src = self.range_source_var.get()
        need_sidecar = src in ("fcpxml", "edl")
        st = "normal" if need_sidecar else "disabled"
        self._ent_sc_r.configure(state=st)
        self._btn_sc_r.configure(state=st)
        self._ent_fps_r.configure(state=st)
        self._lbl_sc_r.configure(text_color=self._pal["text"] if need_sidecar else self._pal["muted"])
        self._lbl_fps_r.configure(text_color=self._pal["text"] if need_sidecar else self._pal["muted"])

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
        for w in (self._tr_hint, self._ff_hint):
            w.configure(text_color=p["muted"])
        for w in (
            self._lbl_range,
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
        self._chk_ow.configure(text_color=p["text"])
        self._progress.configure(progress_color=p["cyan"], fg_color=p["panel_elev"])
        self._log.configure(fg_color=p["panel_elev"], border_color=p["border"], text_color=p["text"])
        self._update_resolve_rows()

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
                        self._combo_preset.configure(values=names)
                        cur = self.preset_var.get().strip()
                        if cur not in names:
                            self.preset_var.set(names[0])
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

        last_cap_min_raw = (self.last_marker_cap_min_var.get() or "").strip().replace(",", ".")
        last_marker_max_sec: float | None = None
        if last_cap_min_raw:
            try:
                m = float(last_cap_min_raw)
                if m <= 0:
                    raise ValueError
                last_marker_max_sec = m * 60.0
            except ValueError:
                messagebox.showerror(
                    "Last marker cap",
                    "Optional 'Last marker max length' must be a positive number (minutes), or leave empty.",
                )
                return

        self._set_busy(True)
        self._lbl_status.configure(text="Resolve…")
        self._progress.set(0)
        self._append_log("\n--- Resolve Deliver ---\n")

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
