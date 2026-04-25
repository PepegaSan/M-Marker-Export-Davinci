# EDL / FCPXML marker autocut

Small **CustomTkinter** tool: load an **FCPXML** (markers) or **EDL** (cuts), point at **one media file**, and **ffmpeg** writes **stream-copy** segments per marker/cut.

## Status

**Beta / narrow use case.** Valid only when your sidecar timebase matches the media you split (same FPS for EDL timecode; FCPXML markers interpreted with the FPS you enter). Always spot-check the first clip.

## Requirements

- Python 3.10+
- `ffmpeg` on `PATH`
- `pip install -r requirements.txt`

## Run

```powershell
python app.py
```

Or double-click `start_gui.bat` (Windows).

## Repo layout

| Item | Role |
|------|------|
| `app.py` | GUI |
| `chapters.py` | FCPXML/EDL parsing + ffmpeg export |
| `theme_palette.py` | Colours (from design kit pattern) |
| `design_kit/` | **Reference only** (UI prompts, examples) |
| `Davinci API start/` | **Reference only** — Resolve scripting helper if you later add Studio render queue (see Google-style flow: init API, `SetCurrentTimeline`, `GetMarkers`, per-range render jobs, timeout). This slim app does **not** call Resolve today. |

## License

MIT unless you specify otherwise.
