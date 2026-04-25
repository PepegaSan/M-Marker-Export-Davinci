#!/usr/bin/env python3
"""Small GUI: FCPXML or EDL + one media file -> ffmpeg stream-copy segments."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Literal

import customtkinter as ctk

from chapters import (
    Chapter,
    chapters_from_edl,
    chapters_from_fcpxml,
    export_with_ffmpeg,
)
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

        self.source_var = tk.StringVar(value="fcpxml")
        self.sidecar_var = tk.StringVar()
        self.media_var = tk.StringVar()
        self.fps_var = tk.StringVar(value="25")
        self.out_dir_var = tk.StringVar(value="exports/clips")
        self.overwrite_var = tk.BooleanVar(value=False)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self._worker: threading.Thread | None = None

        self.title("EDL / FCPXML marker autocut")
        self.geometry("880x640")
        self.minsize(760, 560)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build()
        self._apply_palette()
        self.after(120, self._drain_log)

    def _build(self) -> None:
        top = ctk.CTkFrame(self, corner_radius=0, height=52)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(1, weight=1)
        self._lbl_title = ctk.CTkLabel(
            top,
            text="Marker autocut (FCPXML / EDL + ffmpeg)",
            font=("Segoe UI Semibold", 16),
            fg_color="transparent",
        )
        self._lbl_title.grid(row=0, column=0, padx=14, pady=12, sticky="w")
        self._lbl_status = ctk.CTkLabel(
            top,
            text="Ready",
            font=FONT_UI,
            fg_color="transparent",
        )
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
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 10))
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(6, weight=1)

        r = 0
        self._card_title = ctk.CTkLabel(
            body,
            text="Inputs",
            font=FONT_SECTION,
            fg_color="transparent",
        )
        self._card_title.grid(row=r, column=0, columnspan=3, sticky="w", padx=12, pady=(12, 4))

        r += 1
        self._lbl_src = ctk.CTkLabel(body, text="Sidecar type", font=FONT_UI, fg_color="transparent")
        self._lbl_src.grid(row=r, column=0, sticky="w", padx=12, pady=6)
        self._seg_source = ctk.CTkSegmentedButton(
            body,
            values=["fcpxml", "edl"],
            variable=self.source_var,
            font=("Segoe UI", 12),
        )
        self._seg_source.grid(row=r, column=1, columnspan=2, sticky="ew", padx=10, pady=6)

        r += 1
        self._lbl_sidecar = ctk.CTkLabel(body, text="FCPXML / EDL file", font=FONT_UI, fg_color="transparent")
        self._lbl_sidecar.grid(row=r, column=0, sticky="w", padx=12, pady=6)
        self._ent_sidecar = ctk.CTkEntry(
            body,
            textvariable=self.sidecar_var,
            placeholder_text="Path to .fcpxml / .xml or .edl",
            font=FONT_UI,
        )
        self._ent_sidecar.grid(row=r, column=1, sticky="ew", padx=10, pady=6)
        self._btn_sidecar = ctk.CTkButton(body, text="Browse", width=88, command=self._browse_sidecar)
        self._btn_sidecar.grid(row=r, column=2, padx=10, pady=6)

        r += 1
        self._lbl_media = ctk.CTkLabel(body, text="Media file", font=FONT_UI, fg_color="transparent")
        self._lbl_media.grid(row=r, column=0, sticky="w", padx=12, pady=6)
        self._ent_media = ctk.CTkEntry(
            body,
            textvariable=self.media_var,
            placeholder_text="Video/audio to split (same timeline as sidecar)",
            font=FONT_UI,
        )
        self._ent_media.grid(row=r, column=1, sticky="ew", padx=10, pady=6)
        self._btn_media = ctk.CTkButton(body, text="Browse", width=88, command=self._browse_media)
        self._btn_media.grid(row=r, column=2, padx=10, pady=6)

        r += 1
        self._lbl_fps = ctk.CTkLabel(body, text="FPS (for EDL TC / FCPXML)", font=FONT_UI, fg_color="transparent")
        self._lbl_fps.grid(row=r, column=0, sticky="w", padx=12, pady=6)
        self._ent_fps = ctk.CTkEntry(body, textvariable=self.fps_var, width=120, font=FONT_UI)
        self._ent_fps.grid(row=r, column=1, sticky="w", padx=10, pady=6)

        r += 1
        self._lbl_out = ctk.CTkLabel(body, text="Output folder", font=FONT_UI, fg_color="transparent")
        self._lbl_out.grid(row=r, column=0, sticky="w", padx=12, pady=6)
        self._ent_out = ctk.CTkEntry(body, textvariable=self.out_dir_var, font=FONT_UI)
        self._ent_out.grid(row=r, column=1, columnspan=2, sticky="ew", padx=10, pady=6)

        r += 1
        row_opts = ctk.CTkFrame(body, fg_color="transparent")
        row_opts.grid(row=r, column=1, columnspan=2, sticky="w", padx=10, pady=(4, 8))
        self._chk_overwrite = ctk.CTkCheckBox(
            row_opts,
            text="Overwrite existing clips",
            variable=self.overwrite_var,
            font=FONT_UI,
        )
        self._chk_overwrite.pack(side="left")

        r += 1
        self._progress = ctk.CTkProgressBar(body)
        self._progress.grid(row=r, column=0, columnspan=3, sticky="ew", padx=12, pady=(4, 4))
        self._progress.set(0)

        r += 1
        self._log = ctk.CTkTextbox(body, wrap="word", font=("Consolas", 12))
        self._log.grid(row=r, column=0, columnspan=3, sticky="nsew", padx=10, pady=(4, 10))
        self._log.insert("end", "Pick sidecar + media, then Run.\n")
        self._log.configure(state="disabled")

        bar = ctk.CTkFrame(self, corner_radius=0)
        bar.grid(row=2, column=0, sticky="ew", padx=0, pady=(0, 8))
        self._btn_run = ctk.CTkButton(bar, text="Run autocut", width=140, height=BTN_H, command=self._run)
        self._btn_run.pack(side="left", padx=12, pady=8)

        hint = ctk.CTkLabel(
            bar,
            text="ffmpeg must be on PATH. Uses stream copy (-c copy). EDL: record in/out timecodes.",
            font=FONT_HINT,
            fg_color="transparent",
            anchor="w",
        )
        hint.pack(side="left", padx=8)

    def _browse_sidecar(self) -> None:
        p = filedialog.askopenfilename(
            title="FCPXML or EDL",
            filetypes=[
                ("Sidecar", "*.fcpxml *.xml *.edl"),
                ("All", "*.*"),
            ],
        )
        if p:
            self.sidecar_var.set(p)
            low = p.lower()
            if low.endswith(".edl"):
                self.source_var.set("edl")
            elif low.endswith(".fcpxml") or low.endswith(".xml"):
                self.source_var.set("fcpxml")

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
        for w in (
            self._card_title,
            self._lbl_src,
            self._lbl_sidecar,
            self._lbl_media,
            self._lbl_fps,
            self._lbl_out,
        ):
            w.configure(text_color=p["text"])
        self._seg_source.configure(
            fg_color=p["panel"],
            selected_color=p["cyan_dim"],
            selected_hover_color=p["cyan"],
            unselected_color=p["panel_elev"],
            unselected_hover_color=p["border"],
            text_color=p["text"],
        )
        for entry in (self._ent_sidecar, self._ent_media, self._ent_fps, self._ent_out):
            entry.configure(fg_color=p["panel"], border_color=p["border"], text_color=p["text"])
        self._btn_run.configure(**self._button_kw("primary"))
        for b in (self._btn_sidecar, self._btn_media):
            b.configure(**self._button_kw("ghost"))
        self._chk_overwrite.configure(text_color=p["text"])
        self._progress.configure(progress_color=p["cyan"], fg_color=p["panel_elev"])
        self._log.configure(fg_color=p["panel_elev"], border_color=p["border"], text_color=p["text"])

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
        if line.startswith("[progress] ") and "|" in line:
            try:
                part = line.split("|", 1)[0].replace("[progress]", "").strip()
                a, b = part.split("/", 1)
                done, total = int(a), int(max(int(b), 1))
                self._progress.set(done / total)
                self._lbl_status.configure(text=f"{done}/{total}")
            except (ValueError, IndexError):
                pass

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
            self._btn_run.configure(state="normal")
            if self._lbl_status.cget("text") != "Error":
                self._lbl_status.configure(text="Done")
        self.after(120, self._drain_log)

    def _run(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        sidecar = self.sidecar_var.get().strip()
        media = self.media_var.get().strip()
        if not sidecar or not Path(sidecar).is_file():
            messagebox.showerror("Missing file", "Choose a valid FCPXML or EDL file.")
            return
        if not media or not Path(media).is_file():
            messagebox.showerror("Missing file", "Choose a valid media file.")
            return
        try:
            fps = float((self.fps_var.get() or "25").replace(",", "."))
            if fps <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("FPS", "Enter a positive FPS number (e.g. 25 or 23.976).")
            return

        out_dir = ROOT / (self.out_dir_var.get().strip() or "exports/clips")
        src: Literal["fcpxml", "edl"] = (
            "edl" if self.source_var.get() == "edl" else "fcpxml"
        )

        self._btn_run.configure(state="disabled")
        self._lbl_status.configure(text="Working…")
        self._progress.set(0)
        self._append_log("\n--- run ---\n")

        def work() -> None:
            try:
                path = Path(sidecar)
                media_path = Path(media)
                chapters: list[Chapter]
                if src == "fcpxml":
                    chapters = chapters_from_fcpxml(path, fps)
                else:
                    chapters = chapters_from_edl(path, fps)
                self.log_queue.put(f"Parsed {len(chapters)} segments.\n")
                export_with_ffmpeg(
                    media_path,
                    chapters,
                    fps,
                    out_dir,
                    overwrite=self.overwrite_var.get(),
                    log=lambda s: self.log_queue.put(s),
                )
                self.log_queue.put(f"Output: {out_dir}\n")
            except Exception as exc:
                self.log_queue.put(f"ERROR: {exc}\n")
                self.after(0, lambda: self._lbl_status.configure(text="Error"))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()


def main() -> None:
    AutocutApp().mainloop()


if __name__ == "__main__":
    main()
