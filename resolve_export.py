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


def _clip_timeline_end_rel_exclusive(item: Any, start_abs: int) -> Optional[int]:
    """Right edge of one timeline item as relative exclusive end (same idea as clip stack)."""
    try:
        s_abs = int(item.GetStart())
    except Exception:
        return None
    candidates: List[int] = []
    try:
        candidates.append(int(item.GetEnd()))
    except Exception:
        pass
    try:
        du = int(item.GetDuration())
        if du > 0:
            candidates.append(s_abs + du)
    except Exception:
        pass
    if not candidates:
        return None
    end_excl_abs = min(candidates)
    return max(1, end_excl_abs - int(start_abs))


def _pick_reference_timeline_video_item(timeline: Any) -> Any:
    """Clip under playhead, else first clip on video track 1."""
    try:
        cur = timeline.GetCurrentVideoItem()
        if cur is not None:
            return cur
    except Exception:
        pass
    try:
        items = timeline.GetItemListInTrack("video", 1) or []
        if items:
            return items[0]
    except Exception:
        pass
    return None


def _build_chapters_from_sorted_markers(
    markers: dict,
    keyed: List[Tuple[int, Any]],
    rel_end_ex: int,
    fps: float,
    *,
    include_zero_duration: bool,
    last_marker_max_sec: Optional[float] = None,
    extend_last_marker_segment: bool = True,
    between_markers_only: bool = False,
) -> List[Chapter]:
    """``keyed``: ``(timeline-relative start frame, raw dict key)`` sorted by start.

    If ``between_markers_only`` is True, build **len(keyed) - 1** chapters:
    ``[f[i], f[i+1])`` using the **name** (and index) of the **starting** marker.
    The last marker is only an end boundary — no chapter starts there.
    For a single marker, falls back to the normal one-chapter rules.
    """
    if between_markers_only:
        if len(keyed) < 2:
            return _build_chapters_from_sorted_markers(
                markers,
                keyed,
                rel_end_ex,
                fps,
                include_zero_duration=include_zero_duration,
                last_marker_max_sec=last_marker_max_sec,
                extend_last_marker_segment=extend_last_marker_segment,
                between_markers_only=False,
            )
        chapters_bm: List[Chapter] = []
        seq_bm = 0
        for i in range(len(keyed) - 1):
            start_f = int(keyed[i][0])
            end_ex = min(int(keyed[i + 1][0]), rel_end_ex)
            if end_ex <= start_f or start_f >= rel_end_ex:
                continue
            raw_key = keyed[i][1]
            marker = markers.get(raw_key) or {}
            seq_bm += 1
            name = str(marker.get("name") or f"chapter_{seq_bm:03d}")
            chapters_bm.append(
                Chapter(
                    index=seq_bm,
                    name=name,
                    start_frame=start_f,
                    end_frame_exclusive=end_ex,
                )
            )
        if not chapters_bm:
            raise RuntimeError("No markers found for the selected marker source.")
        return chapters_bm

    chapters: List[Chapter] = []
    seq = 0
    for pos, (rel_start, raw_key) in enumerate(keyed):
        marker = markers[raw_key] or {}
        start_f = int(rel_start)
        try:
            dur = int(float(marker.get("duration", 0) or 0))
        except (TypeError, ValueError):
            dur = 0
        if dur <= 0 and not include_zero_duration:
            continue

        next_start = int(keyed[pos + 1][0]) if pos + 1 < len(keyed) else None

        if dur >= 2:
            end_ex = start_f + dur
            if next_start is not None and end_ex > next_start:
                end_ex = next_start
            elif next_start is None and extend_last_marker_segment:
                # Same as short markers: last segment runs to timeline end (with cap).
                end_ex = rel_end_ex
                if last_marker_max_sec is not None and last_marker_max_sec > 0:
                    cap_ex = start_f + int(last_marker_max_sec * fps)
                    if cap_ex < end_ex:
                        end_ex = cap_ex
        else:
            if next_start is not None:
                end_ex = next_start
            elif not extend_last_marker_segment:
                end_ex = min(start_f + 1, rel_end_ex)
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
        raise RuntimeError("No markers found for the selected marker source.")
    return chapters


def _chapters_from_timeline_markers(
    project: Any,
    timeline: Any,
    *,
    include_zero_duration: bool,
    last_marker_max_sec: Optional[float] = None,
    extend_last_marker_segment: bool = True,
    between_markers_only: bool = False,
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
    keyed = [
        (_marker_frame_to_rel(int(k), start_abs), k) for k in markers.keys()
    ]
    keyed.sort(key=lambda t: t[0])
    chapters = _build_chapters_from_sorted_markers(
        markers,
        keyed,
        rel_end_ex,
        fps,
        include_zero_duration=include_zero_duration,
        last_marker_max_sec=last_marker_max_sec,
        extend_last_marker_segment=extend_last_marker_segment,
        between_markers_only=between_markers_only,
    )
    return chapters, fps, rel_end_ex


def _chapters_from_source_clip_markers(
    project: Any,
    timeline: Any,
    *,
    include_zero_duration: bool,
    last_marker_max_sec: Optional[float] = None,
    extend_last_marker_segment: bool = True,
    between_markers_only: bool = False,
) -> Tuple[List[Chapter], float, int]:
    """Markers from pool + timeline clip, mapped through the reference video item.

    Resolve keeps two stores: ``MediaPoolItem.GetMarkers()`` (keys = source file
    frames) and ``TimelineItem.GetMarkers()`` on the clip (keys = clip offset /
    absolute source frame when in trim — we try absolute in-trim first, else
    ``src_in + offset``). Pool entries win on duplicate timeline positions.
    """
    fps_raw = (
        timeline.GetSetting("timelineFrameRate")
        or project.GetSetting("timelineFrameRate")
        or "25"
    )
    fps = float(str(fps_raw).strip())
    start_abs = _timeline_start_abs_frame(timeline, fps)
    rel_end_global = _timeline_rel_end_exclusive(timeline, start_abs, fps)
    content_end_ex = _timeline_content_end_rel_exclusive(timeline, start_abs)
    if content_end_ex is not None and content_end_ex < rel_end_global:
        rel_end_global = content_end_ex

    item = _pick_reference_timeline_video_item(timeline)
    if item is None:
        raise RuntimeError(
            "No reference video clip: park the playhead on a video clip, "
            "or place a clip on video track 1."
        )
    try:
        mpi = item.GetMediaPoolItem()
    except Exception:
        mpi = None

    clip_cap = _clip_timeline_end_rel_exclusive(item, start_abs)
    rel_end_ex = rel_end_global
    if clip_cap is not None:
        rel_end_ex = min(rel_end_ex, clip_cap)

    try:
        src_in = int(item.GetSourceStartFrame())
    except Exception as exc:
        raise RuntimeError(f"GetSourceStartFrame failed on reference clip: {exc!r}") from exc
    try:
        src_out = int(item.GetSourceEndFrame())
    except Exception:
        src_out = src_in
    try:
        t_start = int(item.GetStart())
    except Exception as exc:
        raise RuntimeError(f"GetStart failed on reference clip: {exc!r}") from exc

    pool_markers: dict = {}
    if mpi is not None:
        try:
            pool_markers = mpi.GetMarkers() or {}
        except Exception:
            pool_markers = {}

    try:
        clip_markers = item.GetMarkers() or {}
    except Exception:
        clip_markers = {}

    if not pool_markers and not clip_markers:
        if mpi is None:
            raise RuntimeError(
                "No Media Pool item and no timeline-clip markers on the reference clip."
            )
        raise RuntimeError(
            "No markers on the pool clip or the timeline clip — add markers in Media or on the clip."
        )

    def _src_f_from_pool_key(raw_k: Any) -> Optional[int]:
        try:
            kk = int(float(raw_k))
        except (TypeError, ValueError):
            return None
        if kk < src_in or kk > src_out:
            return None
        return kk

    def _src_f_from_clip_item_key(raw_k: Any) -> Optional[int]:
        """Resolve uses **clip offset** (from source in-point) for ``TimelineItem.GetMarkers`` keys."""
        try:
            kk = int(float(raw_k))
        except (TypeError, ValueError):
            return None
        if src_in <= kk <= src_out:
            return kk
        abs_f = src_in + kk
        if abs_f < src_in or abs_f > src_out:
            return None
        return abs_f

    markers: dict = {}
    keyed: List[Tuple[int, Any]] = []
    pool_rels: set = set()

    for raw_k, info in pool_markers.items():
        src_f = _src_f_from_pool_key(raw_k)
        if src_f is None:
            continue
        tl_abs = t_start + (src_f - src_in)
        rel = _marker_frame_to_rel(tl_abs, start_abs)
        tag = ("pool", raw_k)
        markers[tag] = info
        keyed.append((rel, tag))
        pool_rels.add(rel)

    for raw_k, info in clip_markers.items():
        src_f = _src_f_from_clip_item_key(raw_k)
        if src_f is None:
            continue
        tl_abs = t_start + (src_f - src_in)
        rel = _marker_frame_to_rel(tl_abs, start_abs)
        if rel in pool_rels:
            continue
        tag = ("clip", raw_k)
        markers[tag] = info
        keyed.append((rel, tag))

    keyed.sort(key=lambda t: t[0])

    chapters = _build_chapters_from_sorted_markers(
        markers,
        keyed,
        rel_end_ex,
        fps,
        include_zero_duration=include_zero_duration,
        last_marker_max_sec=last_marker_max_sec,
        extend_last_marker_segment=extend_last_marker_segment,
        between_markers_only=between_markers_only,
    )
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
    # First frame index on the timeline ruler (often 108000 @ 01:00:00:00).
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
    resolve_app: Any,
    project: Any,
    timeline: Any,
    chapters: Sequence[Chapter],
    fps: float,
    out_dir: Path,
    base_name: str,
    preset_name: Optional[str],
    timeout_s: float,
    log: Callable[[str], None],
    *,
    marks_relative_to_timeline_start: bool,
) -> None:
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    start_abs = _timeline_start_abs_frame(timeline, fps)
    log(
        "Deliver MarkIn/MarkOut use **record-frame indices** (same space as "
        "GetStartFrame() + offset / timeline clip GetStart). Not 0-based "
        "offsets when the timeline start frame is non-zero.\n"
    )
    log(f"Timeline GetStartFrame() (absolute): {start_abs}\n")

    # Renders often ignore range if UI is not on Deliver (Resolve quirk).
    try:
        resolve_app.OpenPage("deliver")
        time.sleep(0.35)
    except Exception as exc:
        log(f"WARN: OpenPage('deliver'): {exc!r}\n")

    saved_marks: Any = None
    try:
        saved_marks = timeline.GetMarkInOut()
    except Exception:
        saved_marks = None

    total = len(chapters)
    for n, c in enumerate(chapters, start=1):
        project.DeleteAllRenderJobs()
        _load_render_preset(project, preset_name, log)
        project.SetCurrentTimeline(timeline)

        # Chapters use half-open ranges relative to GetStartFrame(); Deliver
        # expects inclusive MarkIn/MarkOut in absolute record-frame space.
        rel_in = int(c.start_frame)
        rel_out_inc = int(max(c.start_frame, c.end_frame_exclusive - 1))
        try:
            end_abs_inc = int(timeline.GetEndFrame())
        except Exception:
            end_abs_inc = int(start_abs) + rel_out_inc
        if marks_relative_to_timeline_start:
            abs_in = int(start_abs) + rel_in
            abs_out_inc = int(start_abs) + rel_out_inc
        else:
            # EDL record timecode → frames already in timeline record space.
            abs_in = rel_in
            abs_out_inc = rel_out_inc
        abs_in = max(int(start_abs), min(abs_in, end_abs_inc))
        abs_out_inc = max(abs_in, min(abs_out_inc, end_abs_inc))
        dur_frames = abs_out_inc - abs_in + 1
        mark_in_tc = _frame_to_tc(abs_in, fps)
        mark_out_tc = _frame_to_tc(abs_out_inc, fps)
        safe = slugify_marker_name(c.name)
        custom = f"{base_name}_{c.index:03d}_{safe}"

        # Deliver often follows timeline I/O; align marks with render range.
        try:
            timeline.ClearMarkInOut("all")
        except Exception:
            pass
        try:
            ok_io = timeline.SetMarkInOut(abs_in, abs_out_inc, "all")
            if not ok_io:
                log("WARN: timeline.SetMarkInOut returned False — retry once after short delay.\n")
                time.sleep(0.4)
                ok_io = timeline.SetMarkInOut(abs_in, abs_out_inc, "all")
            if not ok_io:
                log("WARN: timeline.SetMarkInOut still False (Deliver may ignore range).\n")
        except Exception as exc:
            log(f"WARN: timeline.SetMarkInOut: {exc!r}\n")
        # Resolve sometimes applies MarkIn/Out asynchronously; brief settle before render settings.
        time.sleep(0.22)

        settings = {
            "SelectAllFrames": False,
            "MarkIn": abs_in,
            "MarkOut": abs_out_inc,
            "TargetDir": dvr.to_forward(str(out_dir)),
            "CustomName": custom,
        }
        if not project.SetRenderSettings(settings):
            raise RuntimeError(f"SetRenderSettings failed for chapter {c.index}.")
        job_id = project.AddRenderJob()
        if not job_id:
            raise RuntimeError(f"AddRenderJob failed for chapter {c.index}.")
        job_key = str(job_id)
        rel_note = (
            f" +start→record {rel_in}..{rel_out_inc}"
            if marks_relative_to_timeline_start
            else ""
        )
        log(
            f"[progress] {n}/{total} | resolve-render | {custom} "
            f"record_frames {abs_in}..{abs_out_inc} ({dur_frames} fr)"
            f"{rel_note} | approx_TC {mark_in_tc}->{mark_out_tc}\n"
        )
        try:
            project.StartRendering([job_key])
        except TypeError:
            project.StartRendering(job_id)
        started = time.time()
        while project.IsRenderingInProgress():
            if time.time() - started > timeout_s:
                project.StopRendering()
                raise RuntimeError(f"Rendering exceeded {timeout_s:.0f}s timeout.")
            time.sleep(1.0)
        try:
            st = project.GetRenderJobStatus(job_key)
            if isinstance(st, dict):
                log(f"Job status: {st!r}\n")
            elif st is not None:
                log(f"Job status: {st!r}\n")
        except Exception as exc:
            log(f"GetRenderJobStatus failed: {exc!r}\n")

    # Restore user marks if we captured them (best-effort).
    if isinstance(saved_marks, dict):
        try:
            timeline.ClearMarkInOut("all")
            for kind in ("video", "audio"):
                block = saved_marks.get(kind)
                if not isinstance(block, dict):
                    continue
                inn = block.get("in")
                outv = block.get("out")
                if inn is not None and outv is not None:
                    timeline.SetMarkInOut(int(inn), int(outv), kind)
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
    extend_last_marker_segment: bool = True,
    between_markers_only: bool = False,
    timeline_marker_scope: str = "timeline",
    status_callback: Callable[[str], None],
    timeout_s: float = 7200.0,
) -> None:
    """Single COM thread: connect, build chapter list, queue + run Deliver.

    ``range_source``: ``\"timeline\"`` | ``\"fcpxml\"`` | ``\"edl\"``.

    For ``timeline``, ``timeline_marker_scope`` selects **timeline ruler**
    markers (``GetMarkers`` on the timeline) vs **source / clip** markers
    (``MediaPoolItem.GetMarkers`` plus ``TimelineItem.GetMarkers`` on the
    reference video clip).

    ``between_markers_only`` (timeline only): when True, build ``N-1`` chapters
    ``[M_i, M_{i+1})`` so the last marker does not start an extra tail segment.

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
        resolve_app, project, _mp, _root = dvr.connect_resolve(
            status_callback=log,
            auto_launch=True,
        )
        timeline = project.GetCurrentTimeline()
        if timeline is None:
            raise RuntimeError("No current timeline in Resolve.")

        if src == "timeline":
            scope = (timeline_marker_scope or "timeline").strip().lower()
            if scope not in ("timeline", "source_clip"):
                scope = "timeline"
            if scope == "source_clip":
                chapters, fps, rel_end_used = _chapters_from_source_clip_markers(
                    project,
                    timeline,
                    include_zero_duration=include_zero_duration,
                    last_marker_max_sec=last_marker_max_sec,
                    extend_last_marker_segment=extend_last_marker_segment,
                    between_markers_only=between_markers_only,
                )
                marker_note = (
                    "Markers: **source / clip** (MediaPoolItem + TimelineItem.GetMarkers, "
                    "playhead / V1). "
                )
            else:
                chapters, fps, rel_end_used = _chapters_from_timeline_markers(
                    project,
                    timeline,
                    include_zero_duration=include_zero_duration,
                    last_marker_max_sec=last_marker_max_sec,
                    extend_last_marker_segment=extend_last_marker_segment,
                    between_markers_only=between_markers_only,
                )
                marker_note = "Markers: **timeline ruler** (timeline.GetMarkers). "
            if between_markers_only:
                cap_note = ""
                last_mode = (
                    "Between markers: chapters are [M_i, M_{i+1}); "
                    "no chapter from the last marker onward."
                )
            else:
                cap_note = (
                    f" | last-marker cap: {last_marker_max_sec:g}s"
                    if extend_last_marker_segment
                    and last_marker_max_sec
                    and last_marker_max_sec > 0
                    else ""
                )
                last_mode = (
                    "Last segment extends to timeline/clip end (minutes field applies)."
                    if extend_last_marker_segment
                    else "Last segment ends at marker only (marker duration, else 1 frame)."
                )
            log(
                f"Timeline @ {fps:g} fps — {len(chapters)} marker segment(s). "
                f"{marker_note}"
                f"{last_mode} "
                f"rel_end={rel_end_used} (min of GetEndFrame vs clip-stack)"
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
            if src == "edl":
                log(
                    f"Parsed {len(chapters)} segment(s) from EDL @ {fps:g} fps. "
                    "Record IN/OUT are used as **absolute** record frames (no GetStartFrame offset).\n"
                )
            else:
                log(
                    f"Parsed {len(chapters)} segment(s) from FCPXML @ {fps:g} fps. "
                    "Ranges are offset from timeline start → **GetStartFrame()** is added for Deliver.\n"
                )

        project.SetCurrentTimeline(timeline)
        preset_clean = (preset_name or "").strip() or None
        marks_relative_to_timeline_start = src in ("timeline", "fcpxml")
        _render_chapters_sequential(
            resolve_app,
            project,
            timeline,
            chapters,
            fps,
            out_dir,
            base_name.strip() or "chapter",
            preset_clean,
            timeout_s,
            log,
            marks_relative_to_timeline_start=marks_relative_to_timeline_start,
        )
