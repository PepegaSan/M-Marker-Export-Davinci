# M Marker Export (DaVinci Resolve)

Small **CustomTkinter** desktop app: batch **Deliver** in **DaVinci Resolve Studio** from **timeline markers** or from **FCPXML / EDL** ranges. Optional **ffmpeg** tab splits one media file using the same sidecar (no Resolve required).

**UI language:** English only.

## What it does

- **Resolve Studio tab**
  - **Timeline** — Build chapters from markers: **timeline ruler** (`timeline.GetMarkers`) or **source / clip** (`MediaPoolItem` + `TimelineItem.GetMarkers` on the playhead clip, else first clip on video track 1).
  - **Between markers only (default on)** — For *N* markers you get *N−1* exports `[M₁, M₂)`, `[M₂, M₃)` … no extra tail clip starting at the last marker.
  - **Extend last segment** — When “between markers” is off: extend the last chapter to timeline/clip end (with optional minutes cap).
  - **FCPXML / EDL** — Ranges from file; MarkIn/MarkOut aligned to the active timeline timebase.
  - Sequential Deliver jobs, render preset, output folder, logging.
- **ffmpeg tab** — Sidecar + one media file → segment exports (`ffmpeg`, often `-c copy`).
- **Settings (⚙)** — Optional Resolve install paths and default render preset; stored in `user_settings.json` (create from `user_settings.example.json`).

## Requirements

- **Python** 3.10–3.12 (64-bit) on Windows  
- **DaVinci Resolve Studio** with **External scripting = Local** (Resolve tab)  
- **ffmpeg** on `PATH` (ffmpeg tab only)

## Install & run

```bat
install_requirements.bat
```

```bat
start_gui.bat
```

Or: `python app.py`

## One-file `.exe` (optional)

```bat
install_requirements.bat
onefile.bat
```

Output: `dist\MMarkerExport.exe` (see `m_marker_export.spec`). Resolve and ffmpeg are **not** bundled.

## Tested with

- **DaVinci Resolve Studio** 18 / 19 (Windows), scripting enabled  
- **Python** 3.12 (64-bit), **CustomTkinter** 5.2+

## Repo contents (shipped)

| File | Purpose |
|------|---------|
| `app.py` | GUI |
| `resolve_export.py` | Resolve Deliver batch |
| `chapters.py` | FCPXML/EDL + ffmpeg export |
| `davinci_api.py` | Resolve connection helpers |
| `theme_palette.py` | Light/dark palette |

## License

MIT unless stated otherwise.
