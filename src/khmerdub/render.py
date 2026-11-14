"""Final video: blur text, burn Khmer subtitles, put the Khmer audio in."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable

import numpy as np

from . import blur as blurmod
from . import jobs
from .media import (
    ffmpeg_exe,
    ffmpeg_has_filter,
    gpu_encoder,
    nvenc_args,
    read_frames,
    video_info,
)
from .subtitles import write_ass, write_srt

FONTS_DIR = Path(__file__).parent / "fonts"
MAX_FILTER_BOXES = 24  # up to this many fixed boxes are blurred by ffmpeg's own filters
QUALITY = {"fast": ("veryfast", "23"), "balanced": ("faster", "21"), "high": ("medium", "19")}


def _small(n: int, by: int) -> int:
    return max(2, n // by // 2 * 2)


def _box_filters(tracks: list[dict], style: str, start: float, width: int, height: int) -> list[str]:
    """ffmpeg filters that blur fixed boxes during their time ranges (times relative to `start`).
    Returns filtergraph pieces from [v0] to [vb]."""
    parts, label = [], "v0"
    for i, tr in enumerate(tracks):
        k = tr["keys"]
        x0, y0 = max(0, int(k[0][1])), max(0, int(k[0][2]))
        x1, y1 = min(width, int(round(k[0][3]))), min(height, int(round(k[0][4])))
        w, h = (x1 - x0) // 2 * 2, (y1 - y0) // 2 * 2
        if w < 4 or h < 4:
            continue
        a, b = max(0.0, k[0][0] - start), max(0.0, k[-1][0] - start)
        when = f"between(t,{a:.3f},{b:.3f})"
        nxt = f"v{i + 1}"
        if style == "box":  # darken, like the frame-by-frame dark box
            parts.append(f"[{label}]drawbox=x={x0}:y={y0}:w={w}:h={h}:color=black@0.85:t=fill:enable='{when}'[{nxt}]")
        else:
            if style == "pixelate":
                look = f"scale={_small(w, 14)}:{_small(h, 14)}:flags=area,scale={w}:{h}:flags=neighbor"
            else:
                # strong enough that text of the box's height can't be read (ffmpeg's blur on a shrunk copy
                # leaves green streaks, so it blurs the full-size box)
                look = f"gblur=sigma={max(10.0, min(w, h) / 4):.1f}"
            parts.append(f"[{label}]split[{label}a][{label}b]")
            parts.append(f"[{label}b]crop={w}:{h}:{x0}:{y0},{look}[{label}c]")
            parts.append(f"[{label}a][{label}c]overlay={x0}:{y0}:enable='{when}'[{nxt}]")
        label = nxt
    parts.append(f"[{label}]null[vb]")
    return parts


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
    video, audio = Path(video).resolve(), Path(audio).resolve()  # ffmpeg runs inside the work folder
    extra_audio = Path(extra_audio).resolve() if extra_audio is not None else None
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

    box_graph = None
    if timeline and timeline.manual_only and len(timeline.raw) <= MAX_FILTER_BOXES:
        box_graph = _box_filters(timeline.raw, blur_style, start, info.width, info.height)  # ffmpeg blurs them
    use_frames = bool(timeline) and box_graph is None
    if use_frames:  # frames decoded by ffmpeg (OpenCV can't read e.g. AV1), blurred here, piped to the encoder
        vin = ["-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{info.width}x{info.height}", "-r", f"{info.fps:.6f}",
               "-i", "-"]
    else:
        vin = ["-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(video)]

    out = Path(out)
    part = out.with_name(f"{out.stem}.part{out.suffix}")  # swapped in only when complete
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
    if box_graph is not None:  # [0:v] -> fixed-box blur -> subtitles / size -> [vout]
        graph = ";".join(["[0:v]null[v0]", *box_graph, f"[vb]{','.join(vf)}[vout]"])
        maps[1] = "[vout]"
        video_filter = ["-filter_complex", graph]
    else:
        video_filter = ["-vf", ",".join(vf)]
    cmd += maps + video_filter
    if not use_frames:  # ffmpeg reports how far it is (for the progress bar)
        cmd[1:1] = ["-progress", "pipe:1", "-nostats"]
    tail = ["-force_key_frames", "expr:gte(t,n_forced*30)",
            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(part)]
    errlog = workdir / "ffmpeg_render.log"

    def encode(codec: list[str]) -> None:
        _encode(cmd + codec + tail, part, errlog, workdir, video, start, duration, info, timeline, blur_style,
                use_frames, progress)

    x264 = ["-c:v", "libx264", "-preset", preset, "-crf", crf]
    if gpu_encoder():  # NVIDIA card: encode on the graphics card, several times faster
        try:
            encode(nvenc_args(crf))
        except RuntimeError:  # the card's encoder failed (driver, too many videos at once...): the normal way
            log("The graphics card could not make the video; making it the normal way.")
            encode(x264)
    else:
        encode(x264)
    part.replace(out)
    if progress:
        progress(1.0, "Video done")
    return out


def _encode(cmd, part, errlog, workdir, video, start, duration, info, timeline, blur_style, use_frames,
            progress) -> None:
    """Run the encoder (feeding it blurred frames when needed). The finished video is left in `part`."""
    with open(errlog, "w") as ef:
        proc = jobs.popen(cmd, cwd=workdir, stdin=subprocess.PIPE if use_frames else None,
                          stdout=None if use_frames else subprocess.PIPE, stderr=ef, text=not use_frames)
        frames = None
        try:  # whatever goes wrong below, the finally ends both ffmpeg programs
            if use_frames:
                n = int(round(duration * info.fps))
                frames = read_frames(video, start, duration, info.fps, info.width, info.height)
                got = 0
                for i, frame in zip(range(n), frames):
                    got += 1
                    jobs.check()
                    t = start + i / info.fps
                    boxes = timeline.boxes(t)
                    if boxes:
                        blurmod.apply(frame, boxes, blur_style)
                    proc.stdin.write(memoryview(np.ascontiguousarray(frame)))
                    if progress and i % 100 == 0:
                        progress(i / max(1, n), f"Making video… {t / 60:.1f}/{(start + duration) / 60:.1f} min")
                if not got:
                    raise RuntimeError("Could not read the video's picture. The file may be damaged.")
                proc.stdin.close()
            else:
                for line in proc.stdout:  # "out_time_us=12345678" every half second
                    if progress and line.startswith("out_time_us="):
                        try:
                            t = int(line.split("=", 1)[1]) / 1e6
                        except ValueError:  # "N/A" at the very start
                            continue
                        progress(t / max(1e-6, duration),
                                 f"Making video… {(start + t) / 60:.1f}/{(start + duration) / 60:.1f} min")
            proc.wait()
        except (BrokenPipeError, OSError):  # ffmpeg stopped early (on Windows: OSError); its log is shown below
            proc.wait()
        except jobs.Stopped:
            proc.kill()
            proc.wait()
        finally:
            if frames is not None:
                frames.close()
            if proc.poll() is None:  # left early (an error): don't leave the encoder or its half file behind
                proc.kill()
                proc.wait()
                part.unlink(missing_ok=True)
            jobs.done(proc)
    if jobs.requested() or proc.returncode != 0:
        part.unlink(missing_ok=True)  # the previous video (if any) stays as it was
        if jobs.requested():
            raise jobs.Stopped()
        raise RuntimeError(f"ffmpeg failed while making the video:\n{errlog.read_text()[-3000:]}")
