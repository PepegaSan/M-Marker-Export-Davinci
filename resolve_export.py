"""DaVinci Resolve Studio: queue Deliver jobs per chapter (marker or sidecar ranges)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence, Tuple

import davinci_api as dvr
from chapters import Chapter, chapters_from_edl, chapters_from_fcpxml, slugify_marker_name


def list_render_presets_sync(
    *,
    status_callback: Optional[Callable[[str], None]] = None,
) -> List[str]:
    with dvr.scripting_thread():
        _resolve, project, _mp, _root = dvr.connect_resolve(
            status_callback=status_callback,
            auto_launch=True,
        )
        return dvr.list_render_presets(project)


def _chapters_from_timeline_markers(
    project: Any,
    timeline: Any,
    *,
    include_zero_duration: bool,
) -> Tuple[List[Chapter], float]:
    fps_raw = (
        timeline.GetSetting("timelineFrameRate")
        or project.GetSetting("timelineFrameRate")
        or "25"
    )
    fps = float(str(fps_raw).strip())
    markers = timeline.GetMarkers() or {}
    chapters: List[Chapter] = []
    for i, frame_id in enumerate(sorted(markers.keys()), start=1):
        marker = markers[frame_id] or {}
        start_f = int(frame_id)
        dur = int(marker.get("duration", 0) or 0)
        if dur <= 0 and not include_zero_duration:
            continue
        if dur <= 0:
            end_ex = start_f + 1
        else:
            end_ex = start_f + dur
        name = str(marker.get("name") or f"chapter_{i:03d}")
        chapters.append(
            Chapter(
                index=i,
                name=name,
                start_frame=start_f,
                end_frame_exclusive=end_ex,
            )
        )
    if not chapters:
        raise RuntimeError("No markers found on the current timeline.")
    return chapters, fps


def _load_render_preset(project: Any, preset_name: Optional[str], log: Callable[[str], None]) -> None:
    tried: List[str] = []
    loaded = False
    chain: Tuple[Optional[str], ...] = (preset_name, *dvr.DEFAULT_RENDER_PRESETS)
    for candidate in chain:
        if not candidate or candidate in tried:
            continue
        tried.append(candidate)
        if project.LoadRenderPreset(candidate):
            log(f"Render preset loaded: {candidate}\n")
            loaded = True
            break
    if not loaded:
        raise RuntimeError(
            "Could not load any render preset. Tried: "
            + ", ".join(tried)
            + ". Type an exact Deliver preset name."
        )


def _queue_resolve_jobs(
    project: Any,
    chapters: Sequence[Chapter],
    out_dir: Path,
    base_name: str,
    preset_name: Optional[str],
    timeout_s: float,
    log: Callable[[str], None],
) -> None:
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    project.DeleteAllRenderJobs()
    _load_render_preset(project, preset_name, log)

    total = len(chapters)
    for n, c in enumerate(chapters, start=1):
        mark_in = c.start_frame
        mark_out_inclusive = max(c.start_frame, c.end_frame_exclusive - 1)
        safe = slugify_marker_name(c.name)
        custom = f"{base_name}_{c.index:03d}_{safe}"
        settings = {
            "SelectAllFrames": False,
            "MarkIn": mark_in,
            "MarkOut": mark_out_inclusive,
            "TargetDir": dvr.to_forward(str(out_dir)),
            "CustomName": custom,
        }
        if not project.SetRenderSettings(settings):
            raise RuntimeError(f"SetRenderSettings failed for chapter {c.index}.")
        job_id = project.AddRenderJob()
        if not job_id:
            raise RuntimeError(f"AddRenderJob failed for chapter {c.index}.")
        log(f"[progress] {n}/{total} | resolve-queue | {custom}\n")

    jobs = project.GetRenderJobList() or []
    if not jobs:
        raise RuntimeError("No render jobs were queued.")
    log(f"Queued {len(jobs)} Resolve render jobs. Starting…\n")

    project.StartRendering()
    started = time.time()
    while project.IsRenderingInProgress():
        if time.time() - started > timeout_s:
            project.StopRendering()
            raise RuntimeError(f"Rendering exceeded {timeout_s:.0f}s timeout.")
        time.sleep(1.0)
    log("Resolve batch render finished.\n")


def run_resolve_deliver(
    *,
    range_source: str,
    sidecar_path: Optional[Path],
    fps_override: Optional[float],
    out_dir: Path,
    base_name: str,
    preset_name: Optional[str],
    include_zero_duration: bool,
    status_callback: Callable[[str], None],
    timeout_s: float = 7200.0,
) -> None:
    """Single COM thread: connect, build chapter list, queue + run Deliver.

    ``range_source``: ``\"timeline\"`` | ``\"fcpxml\"`` | ``\"edl\"``.

    For ``fcpxml`` / ``edl``, ranges are applied as MarkIn/MarkOut on the
    **current** timeline — they must match that timeline's timebase (same
    idea as record timecode in the sidecar matching your edit).
    """
    src = range_source.strip().lower()
    if src not in ("timeline", "fcpxml", "edl"):
        raise ValueError(f"Unknown range source: {range_source!r}")

    def log(msg: str) -> None:
        status_callback(msg)

    with dvr.scripting_thread():
        _resolve, project, _mp, _root = dvr.connect_resolve(
            status_callback=log,
            auto_launch=True,
        )
        timeline = project.GetCurrentTimeline()
        if timeline is None:
            raise RuntimeError("No current timeline in Resolve.")

        if src == "timeline":
            chapters, fps = _chapters_from_timeline_markers(
                project, timeline, include_zero_duration=include_zero_duration
            )
            log(f"Timeline @ {fps:g} fps — {len(chapters)} marker segment(s).\n")
        else:
            if not sidecar_path or not sidecar_path.is_file():
                raise RuntimeError("Choose a valid FCPXML or EDL file.")
            if fps_override is None or fps_override <= 0:
                raise RuntimeError("Enter a positive FPS for FCPXML/EDL.")
            fps = float(fps_override)
            if src == "fcpxml":
                chapters = chapters_from_fcpxml(sidecar_path, fps)
            else:
                chapters = chapters_from_edl(sidecar_path, fps)
            log(
                f"Parsed {len(chapters)} segment(s) from sidecar @ {fps:g} fps. "
                "MarkIn/MarkOut use these as **timeline** frame numbers.\n"
            )

        project.SetCurrentTimeline(timeline)
        preset_clean = (preset_name or "").strip() or None
        _queue_resolve_jobs(
            project,
            chapters,
            out_dir,
            base_name.strip() or "chapter",
            preset_clean,
            timeout_s,
            log,
        )
