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


def _timeline_rel_end_exclusive(timeline: Any, start_abs: int, fps: float) -> int:
    """Half-open timeline end in **relative** frames: ``[0, rel_end_exclusive)``."""
    try:
        end_abs_inc = int(timeline.GetEndFrame())
        startf = int(start_abs) if start_abs else 0
        return max(1, end_abs_inc - startf + 1)
    except Exception:
        fps_i = max(1, int(round(fps)))
        return fps_i * 3600 * 24


def _timeline_content_end_rel_exclusive(timeline: Any, start_abs: int) -> Optional[int]:
    """Right edge of **actual media** on video tracks, as relative exclusive end frame.

    For each clip we take the **tighter** of ``GetEnd()`` and ``GetStart()+GetDuration()``
    when both exist (API quirks / handles can make ``GetEnd()`` sit past real media).
    Across all video tracks we then take the **maximum** (rightmost timeline edge).
    """
    startf = int(start_abs) if start_abs else 0
    max_end_excl_abs: Optional[int] = None
    try:
        n = int(timeline.GetTrackCount("video") or 0)
    except Exception:
        n = 0
    for ti in range(1, n + 1):
        try:
            items = timeline.GetItemListInTrack("video", ti) or []
        except Exception:
            items = []
        for it in items:
            try:
                s_abs = int(it.GetStart())
            except Exception:
                continue
            candidates: List[int] = []
            try:
                candidates.append(int(it.GetEnd()))
            except Exception:
                pass
            try:
                du = int(it.GetDuration())
                if du > 0:
                    candidates.append(s_abs + du)
            except Exception:
                pass
            if not candidates:
                continue
            end_excl_abs = min(candidates)
            max_end_excl_abs = (
                end_excl_abs
                if max_end_excl_abs is None
                else max(max_end_excl_abs, end_excl_abs)
            )
    if max_end_excl_abs is None:
        return None
    rel_excl = max_end_excl_abs - startf
    return max(rel_excl, 1)


def _marker_frame_to_rel(frame_id: int, start_abs: int) -> int:
    """Resolve marker keys may be absolute (>= timeline start) or already relative."""
    f = int(frame_id)
    if start_abs and f >= start_abs:
        return f - start_abs
    return f


def _chapters_from_timeline_markers(
    project: Any,
    timeline: Any,
    *,
    include_zero_duration: bool,
    last_marker_max_sec: Optional[float] = None,
) -> Tuple[List[Chapter], float, int]:
    fps_raw = (
        timeline.GetSetting("timelineFrameRate")
        or project.GetSetting("timelineFrameRate")
        or "25"
    )
    fps = float(str(fps_raw).strip())
    start_abs = _timeline_start_abs_frame(timeline, fps)
    rel_end_ex = _timeline_rel_end_exclusive(timeline, start_abs, fps)
    content_end_ex = _timeline_content_end_rel_exclusive(timeline, start_abs)
    if content_end_ex is not None and content_end_ex < rel_end_ex:
        rel_end_ex = content_end_ex

    markers = timeline.GetMarkers() or {}
    # Preserve original dict keys (type may vary) but sort by relative frame.
    keyed = [
        (_marker_frame_to_rel(int(k), start_abs), k) for k in markers.keys()
    ]
    keyed.sort(key=lambda t: t[0])
    chapters: List[Chapter] = []
    seq = 0
    for pos, (rel_start, raw_key) in enumerate(keyed):
        marker = markers[raw_key] or {}
        start_f = int(rel_start)
        dur = int(marker.get("duration", 0) or 0)
        if dur <= 0 and not include_zero_duration:
            continue

        next_start = int(keyed[pos + 1][0]) if pos + 1 < len(keyed) else None

        # Resolve often leaves marker duration at 0 or 1 when you only tap "M".
        # MarkIn==MarkOut produces broken/unplayable outputs — extend to next marker.
        if dur >= 2:
            end_ex = start_f + dur
            if next_start is not None and end_ex > next_start:
                end_ex = next_start
        else:
            if next_start is not None:
                end_ex = next_start
            else:
                end_ex = rel_end_ex
                if last_marker_max_sec is not None and last_marker_max_sec > 0:
                    cap_ex = start_f + int(last_marker_max_sec * fps)
                    if cap_ex < end_ex:
                        end_ex = cap_ex

        end_ex = max(start_f + 1, min(end_ex, rel_end_ex))
        if start_f >= rel_end_ex:
            continue

        seq += 1
        name = str(marker.get("name") or f"chapter_{seq:03d}")
        chapters.append(
            Chapter(
                index=seq,
                name=name,
                start_frame=start_f,
                end_frame_exclusive=end_ex,
            )
        )
    if not chapters:
        raise RuntimeError("No markers found on the current timeline.")
    return chapters, fps, rel_end_ex


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


def _parse_tc_to_frame(tc: str, fps: float) -> int:
    parts = (tc or "00:00:00:00").strip().split(":")
    if len(parts) != 4:
        return 0
    try:
        hh, mm, ss, ff = (int(p) for p in parts)
    except ValueError:
        return 0
    fps_i = max(1, int(round(fps)))
    return (((hh * 60 + mm) * 60) + ss) * fps_i + ff


def _frame_to_tc(frame: int, fps: float) -> str:
    fps_i = max(1, int(round(fps)))
    frame = max(0, int(frame))
    hh = frame // (fps_i * 3600)
    rem = frame % (fps_i * 3600)
    mm = rem // (fps_i * 60)
    rem = rem % (fps_i * 60)
    ss = rem // fps_i
    ff = rem % fps_i
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def _timeline_start_abs_frame(timeline: Any, fps: float) -> int:
    # Resolve timelines often start at 01:00:00:00. MarkIn/MarkOut behave
    # more reliably when set as absolute timecode, not raw relative frame ints.
    try:
        sf = timeline.GetStartFrame()
        if sf is not None:
            return int(sf)
    except Exception:
        pass
    try:
        stc = timeline.GetStartTimecode()
        if stc:
            return _parse_tc_to_frame(str(stc), fps)
    except Exception:
        pass
    return 0


def _render_chapters_sequential(
    project: Any,
    timeline: Any,
    chapters: Sequence[Chapter],
    fps: float,
    out_dir: Path,
    base_name: str,
    preset_name: Optional[str],
    timeout_s: float,
    log: Callable[[str], None],
) -> None:
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    start_abs = _timeline_start_abs_frame(timeline, fps)
    log(
        "Deliver expects MarkIn/MarkOut as **integer timeline-relative frames** "
        "(see Resolve scripting reference). Using that — not timecode strings.\n"
    )
    log(f"Timeline start frame (absolute, for log only): {start_abs}\n")

    total = len(chapters)
    for n, c in enumerate(chapters, start=1):
        project.DeleteAllRenderJobs()
        _load_render_preset(project, preset_name, log)
        project.SetCurrentTimeline(timeline)

        # Official API: MarkIn / MarkOut are int, inclusive, timeline-relative from 0.
        mark_in = int(c.start_frame)
        mark_out_inclusive = int(max(c.start_frame, c.end_frame_exclusive - 1))
        dur_frames = mark_out_inclusive - mark_in + 1
        mark_in_tc = _frame_to_tc(start_abs + mark_in, fps)
        mark_out_tc = _frame_to_tc(start_abs + mark_out_inclusive, fps)
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
        log(
            f"[progress] {n}/{total} | resolve-render | {custom} "
            f"rel_frames {mark_in}..{mark_out_inclusive} ({dur_frames} fr) "
            f"approx_TC {mark_in_tc}->{mark_out_tc}\n"
        )
        project.StartRendering(job_id)
        started = time.time()
        while project.IsRenderingInProgress():
            if time.time() - started > timeout_s:
                project.StopRendering()
                raise RuntimeError(f"Rendering exceeded {timeout_s:.0f}s timeout.")
            time.sleep(1.0)
        try:
            st = project.GetRenderJobStatus(job_id)
            if isinstance(st, dict):
                log(f"Job finished: {st.get('JobStatus', st)!r}\n")
        except Exception:
            pass
    log("Resolve sequential render finished.\n")


def run_resolve_deliver(
    *,
    range_source: str,
    sidecar_path: Optional[Path],
    fps_override: Optional[float],
    out_dir: Path,
    base_name: str,
    preset_name: Optional[str],
    include_zero_duration: bool,
    last_marker_max_sec: Optional[float] = None,
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
            chapters, fps, rel_end_used = _chapters_from_timeline_markers(
                project,
                timeline,
                include_zero_duration=include_zero_duration,
                last_marker_max_sec=last_marker_max_sec,
            )
            cap_note = (
                f" | last-marker cap: {last_marker_max_sec:g}s"
                if last_marker_max_sec and last_marker_max_sec > 0
                else ""
            )
            log(
                f"Timeline @ {fps:g} fps — {len(chapters)} marker segment(s). "
                f"Extend-to boundary for last marker (no next marker): rel_end={rel_end_used} "
                "(min of GetEndFrame vs clip-stack)"
                f"{cap_note}.\n"
            )
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
        _render_chapters_sequential(
            project,
            timeline,
            chapters,
            fps,
            out_dir,
            base_name.strip() or "chapter",
            preset_clean,
            timeout_s,
            log,
        )
