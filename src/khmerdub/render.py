"""Final video: blur text, burn Khmer subtitles, put the Khmer audio in."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable

import numpy as np

from . import blur as blurmod
from .media import ffmpeg_exe, ffmpeg_has_filter, video_info
from .subtitles import write_ass, write_srt

FONTS_DIR = Path(__file__).parent / "fonts"
QUALITY = {"fast": ("veryfast", "23"), "balanced": ("faster", "21"), "high": ("medium", "19")}


def render(
    video: Path,
    audio: Path,
    out: Path,
    workdir: Path,
    sub_lines: list[tuple[float, float, str]] | None,
    subtitles: str = "burn",  # burn | soft | none
    subtitle_size: float = 1.0,
    timeline: blurmod.Timeline | None = None,
    blur_style: str = "blur",
    quality: str = "balanced",
    resolution: str = "original",
    extra_audio: Path | None = None,
    sub_style: dict | None = None,
    start: float = 0.0,
    duration: float | None = None,
    progress: Callable[[float, str], None] | None = None,
    log: Callable[[str], None] = print,
) -> Path:
    import cv2

    info = video_info(video)
    total = info.duration
    duration = duration if duration is not None else max(0.0, total - start)
    preset, crf = QUALITY.get(quality, QUALITY["balanced"])

    if subtitles == "burn" and sub_lines and not ffmpeg_has_filter("ass"):
        log("This ffmpeg can't burn subtitles (no libass); adding them as a subtitle track instead.")
        subtitles = "soft"

    vf = []
    if subtitles == "burn" and sub_lines:
        fonts = workdir / "fonts"
        fonts.mkdir(exist_ok=True)
        for f in FONTS_DIR.glob("*.ttf"):
            if not (fonts / f.name).exists():
                shutil.copy(f, fonts / f.name)
        write_ass(sub_lines, workdir / "render.ass", info.width, info.height, subtitle_size, offset=start,
                  **(sub_style or {}))
        vf.append("ass=render.ass:fontsdir=fonts")  # relative paths: avoids Windows path escaping
    if resolution not in ("", "original") and min(info.width, info.height) > int(resolution):
        r = int(resolution)  # 1080p/720p/480p is the short side, so vertical videos keep their shape
        vf.append(f"scale=-2:{r}" if info.width >= info.height else f"scale={r}:-2")
    vf.append("format=yuv420p")

    use_frames = bool(timeline)
    cap = None
    if use_frames:
        cap = cv2.VideoCapture(str(video))
        if start:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(start * info.fps)))
        ok, first = cap.read()
        if not ok:
            raise RuntimeError("Could not read video frames")
        h, w = first.shape[:2]
        vin = ["-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{info.fps:.6f}", "-i", "-"]
    else:
        vin = ["-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(video)]

    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *vin,
           "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(audio)]
    maps = ["-map", "0:v:0", "-map", "1:a:0", "-metadata:s:a:0", "language=khm", "-metadata:s:a:0", "title=Khmer",
            "-disposition:a:0", "default"]
    n_in = 2
    if extra_audio is not None and Path(extra_audio).exists():
        cmd += ["-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(extra_audio)]
        maps += ["-map", f"{n_in}:a:0", "-metadata:s:a:1", "language=zho", "-metadata:s:a:1",
                 "title=Chinese (original)", "-disposition:a:1", "0"]
        n_in += 1
    if subtitles == "soft" and sub_lines:
        srt = workdir / "render.srt"
        write_srt([(a - start, b - start, t) for a, b, t in sub_lines if b > start], srt)
        cmd += ["-i", str(srt)]
        maps += ["-map", f"{n_in}:s:0", "-c:s", "mov_text", "-metadata:s:s:0", "language=khm"]
    cmd += maps + ["-vf", ",".join(vf), "-c:v", "libx264", "-preset", preset, "-crf", crf,
                   "-force_key_frames", "expr:gte(t,n_forced*30)",
                   "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)]

    errlog = workdir / "ffmpeg_render.log"
    with open(errlog, "w") as ef:
        proc = subprocess.Popen(cmd, cwd=workdir, stdin=subprocess.PIPE if use_frames else None, stderr=ef)
        try:
            if use_frames:
                n = int(round(duration * info.fps))
                frame = first
                for i in range(n):
                    if i:
                        ok, frame = cap.read()
                        if not ok:
                            break
                    t = start + i / info.fps
                    boxes = timeline.boxes(t)
                    if boxes:
                        blurmod.apply(frame, boxes, blur_style)
                    proc.stdin.write(memoryview(np.ascontiguousarray(frame)))
                    if progress and i % 100 == 0:
                        progress(i / max(1, n), f"Making video… {t / 60:.1f}/{(start + duration) / 60:.1f} min")
                proc.stdin.close()
            elif progress:
                progress(0.5, "Making video…")
            proc.wait()
        except (BrokenPipeError, OSError):  # ffmpeg stopped early (on Windows: OSError); its log is shown below
            proc.wait()
        finally:
            if cap is not None:
                cap.release()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed while making the video:\n{errlog.read_text()[-3000:]}")
    if progress:
        progress(1.0, "Video done")
    return out
