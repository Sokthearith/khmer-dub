"""Cut tool: keep a time range and/or split a video into parts of N minutes.

Uses stream copy (no re-encoding), so even a 1-hour episode is cut in seconds.
Cuts land on keyframes: exact for videos made by Khmer Dub (they get a keyframe
every 30 s), within a few seconds for other videos.
"""

from __future__ import annotations

import glob
import re
from pathlib import Path

from .media import run_ffmpeg, video_info


def parse_time(value) -> float | None:
    """'90', '1:30', '01:02:03', '1:30.5' or a number -> seconds. Empty -> None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    if not re.fullmatch(r"\d+(:\d{1,2}){0,2}(\.\d+)?", s):
        raise ValueError(f"Can't read the time {value!r}. Use minutes:seconds, like 12:30.")
    total = 0.0
    for part in s.split(":"):
        total = total * 60 + float(part)
    return total


def fmt(t: float) -> str:
    t = int(round(t))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def cut(video: Path, out_dir: Path, every_minutes: float | None = None,
        start=None, end=None, name: str | None = None) -> list[Path]:
    """Keep [start, end] (optional) and split it into parts of `every_minutes` (optional)."""
    video, out_dir = Path(video), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dur = video_info(video).duration
    a = max(0.0, parse_time(start) or 0.0)
    b = parse_time(end)
    b = min(b, dur) if (b and dur) else (b or dur)
    if b and b <= a:
        raise ValueError("The end time must be after the start time.")
    stem = name or video.stem
    ext = video.suffix.lower() if video.suffix.lower() in (".mp4", ".mkv", ".mov") else ".mp4"
    rng = (["-ss", f"{a:.3f}"] if a else []) + ["-i", str(video)] + (["-t", f"{b - a:.3f}"] if b else [])
    common = ["-map", "0", "-c", "copy", "-avoid_negative_ts", "make_zero"]

    for old in out_dir.glob(f"{glob.escape(stem)}_part*{ext}"):
        old.unlink()
    if every_minutes and every_minutes > 0 and (not b or (b - a) > every_minutes * 60 + 1):
        pattern = out_dir / f"{stem.replace('%', '%%')}_part%02d{ext}"
        run_ffmpeg([*rng, *common, "-f", "segment", "-segment_time", f"{every_minutes * 60:.3f}",
                    "-reset_timestamps", "1", "-segment_start_number", "1", str(pattern)])
        parts = sorted(out_dir.glob(f"{glob.escape(stem)}_part*{ext}"))
    else:
        label = f"{fmt(a)}-{fmt(b)}".replace(":", ".") if b else fmt(a).replace(":", ".")
        out = out_dir / f"{stem}_{label}{ext}"
        run_ffmpeg([*rng, *common, str(out)])
        parts = [out]
    if not parts:
        raise RuntimeError("Nothing was cut. Check the times.")
    return parts
