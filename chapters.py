"""Parse FCPXML/EDL into chapter ranges and split media with ffmpeg."""
from __future__ import annotations

import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Sequence


@dataclass
class Chapter:
    index: int
    name: str
    start_frame: int
    end_frame_exclusive: int

    @property
    def duration_frames(self) -> int:
        return max(0, self.end_frame_exclusive - self.start_frame)


def _slug(value: str) -> str:
    value = re.sub(r"[^\w\s.-]", "_", value, flags=re.UNICODE).strip()
    value = re.sub(r"\s+", "_", value)
    return value or "chapter"


def _parse_tc(tc: str, fps: float) -> int:
    m = re.match(r"^\s*(\d+):(\d+):(\d+):(\d+)\s*$", tc or "")
    if not m:
        raise ValueError(f"Invalid timecode: {tc!r}")
    h, mi, s, fr = (int(x) for x in m.groups())
    fps_i = int(round(fps))
    return (((h * 60 + mi) * 60) + s) * fps_i + fr


def _seconds_expr_to_seconds(expr: str) -> float:
    expr = (expr or "").strip()
    if not expr:
        return 0.0
    if expr.endswith("s"):
        expr = expr[:-1]
    if "/" in expr:
        num, den = expr.split("/", 1)
        return float(num) / float(den)
    return float(expr)


def chapters_from_fcpxml(path: Path, fps: float) -> List[Chapter]:
    tree = ET.parse(path)
    root = tree.getroot()
    chapters: List[Chapter] = []
    idx = 0
    for marker in root.findall(".//marker"):
        idx += 1
        start_s = _seconds_expr_to_seconds(marker.attrib.get("start", "0s"))
        dur_s = _seconds_expr_to_seconds(marker.attrib.get("duration", "0s"))
        start_f = int(round(start_s * fps))
        dur_f = max(1, int(round(dur_s * fps)))
        end_ex = start_f + dur_f
        name = (
            marker.attrib.get("value", "")
            or marker.attrib.get("note", "")
            or f"chapter_{idx:03d}"
        )
        chapters.append(
            Chapter(
                index=idx,
                name=name,
                start_frame=start_f,
                end_frame_exclusive=end_ex,
            )
        )
    if not chapters:
        raise RuntimeError("No <marker> tags found in FCPXML.")
    return chapters


def chapters_from_edl(path: Path, fps: float) -> List[Chapter]:
    line_re = re.compile(
        r"^\s*(\d+)\s+\S+\s+V\s+C\s+"
        r"(\d\d:\d\d:\d\d:\d\d)\s+(\d\d:\d\d:\d\d:\d\d)\s+"
        r"(\d\d:\d\d:\d\d:\d\d)\s+(\d\d:\d\d:\d\d:\d\d)"
    )
    chapters: List[Chapter] = []
    idx = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            m = line_re.match(raw)
            if not m:
                continue
            idx += 1
            rec_in = _parse_tc(m.group(4), fps)
            rec_out = _parse_tc(m.group(5), fps)
            if rec_out <= rec_in:
                continue
            chapters.append(
                Chapter(
                    index=idx,
                    name=f"chapter_{idx:03d}",
                    start_frame=rec_in,
                    end_frame_exclusive=rec_out,
                )
            )
    if not chapters:
        raise RuntimeError("No cuts found in EDL (expected CMX-style video cut lines).")
    return chapters


def export_with_ffmpeg(
    media_file: Path,
    chapters: Sequence[Chapter],
    fps: float,
    out_dir: Path,
    *,
    overwrite: bool = False,
    log: Callable[[str], None] | None = None,
) -> None:
    def _log(msg: str) -> None:
        if log:
            log(msg)

    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(chapters)
    for n, c in enumerate(chapters, start=1):
        start_s = c.start_frame / fps
        dur_s = c.duration_frames / fps
        name = f"{c.index:03d}_{_slug(c.name)}"
        out_file = out_dir / f"{name}{media_file.suffix}"

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y" if overwrite else "-n",
            "-ss",
            f"{start_s:.6f}",
            "-i",
            str(media_file),
            "-t",
            f"{dur_s:.6f}",
            "-c",
            "copy",
            str(out_file),
        ]
        _log(f"[progress] {n}/{total} | {out_file.name} ({dur_s:.3f}s)\n")
        subprocess.run(cmd, check=True)
