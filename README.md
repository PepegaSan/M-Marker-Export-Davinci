# EDL / FCPXML marker autocut

Small **CustomTkinter** tool focused on **DaVinci Resolve Studio**: queue **Deliver** jobs so each timeline marker (or each range from an **FCPXML** / **EDL** sidecar) exports as its own file. An **ffmpeg** tab remains as a fallback when you only have a flat media file and no Resolve session.

## Status

**Beta.** Resolve scripting, preset names, sidecar-to-timeline frame alignment, and ffmpeg trims are easy to get wrong on edge cases. Spot-check outputs before long batch runs.

## Requirements

- Python 3.10+
- **Resolve Studio** with **External scripting = Local** (for the Resolve tab)
- **`davinci_api.py`** in the project root (shipped here; mirrors `Davinci API start/davinci_api.py`)
- **ffmpeg** on `PATH` (only for the ffmpeg fallback tab)
- `pip install -r requirements.txt`

## Run

```powershell
python app.py
```

Or double-click `start_gui.bat` (Windows).

## Resolve tab (main)

1. Open project + timeline in Resolve.
2. Choose range source:
   - **timeline** — `GetMarkers()` on the active timeline (duration per marker).
   - **fcpxml** / **edl** — parse ranges; **MarkIn/MarkOut** use those as **timeline frame numbers** (your edit must match that timebase).
3. Set Deliver output folder, preset (type manually or **Load presets**), and output base name.
4. **Run Deliver** — clears the render queue, queues one job per segment, starts rendering with a timeout.

Uses one `scripting_thread()` block for connect → build chapter list → queue jobs → render (same patterns as Blackmagic’s scripting notes: forward slashes via `to_forward`, preset fallback, `DeleteAllRenderJobs`, bounded render wait).

## ffmpeg tab (fallback)

Sidecar + one media file → `ffmpeg -c copy` segments. Same FPS / timebase caveats as before.

## Repo layout

| Item | Role |
|------|------|
| `app.py` | GUI (tabs: Resolve · ffmpeg) |
| `resolve_export.py` | Resolve Deliver batch |
| `chapters.py` | FCPXML/EDL parsing + ffmpeg export |
| `davinci_api.py` | Resolve connection + render helpers (runtime) |
| `theme_palette.py` | Colours |
| `design_kit/` | **Reference only** |
| `Davinci API start/` | **Reference copy** of the same API kit (optional duplicate) |

## License

MIT unless you specify otherwise.
