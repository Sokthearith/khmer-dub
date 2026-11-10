"""ffmpeg discovery and small audio/video helpers.

Uses the system ffmpeg when it exists (usually has more features), otherwise the
static ffmpeg bundled by the `imageio-ffmpeg` package, so friends don't need to
install anything by hand.
"""

from __future__ import annotations

import functools
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SR = 44100  # working sample rate for mixing


@functools.cache
def ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "ffmpeg not found. Install it (https://ffmpeg.org) or `pip install imageio-ffmpeg`."
        ) from e


@functools.cache
def ffmpeg_has_filter(name: str) -> bool:
    out = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-filters"], capture_output=True, text=True
    ).stdout
    return any(line.split()[1:2] == [name] for line in out.splitlines() if line.strip())


def run_ffmpeg(args: list[str], cwd: str | Path | None = None) -> None:
    from . import jobs

    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args]
    p = jobs.popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        _, stderr = p.communicate()
    finally:
        jobs.done(p)
    if jobs.requested():  # Stop ended it: don't leave a half-written file behind
        if p.returncode != 0 and args and not str(args[-1]).startswith("-"):
            (Path(cwd or ".") / str(args[-1])).unlink(missing_ok=True)
        raise jobs.Stopped()
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd)}\n{stderr[-3000:]}")


def load_audio(path: str | Path, sr: int = SR, channels: int = 2) -> np.ndarray:
    """Decode any audio/video file to float32 array shaped (samples, channels)."""
    cmd = [
        ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-vn", "-ac", str(channels), "-ar", str(sr), "-f", "f32le", "-",
    ]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"Could not read audio from {path}:\n{p.stderr.decode()[-2000:]}")
    a = np.frombuffer(p.stdout, dtype=np.float32)
    return a.reshape(-1, channels).copy()


def save_wav(path: str | Path, audio: np.ndarray, sr: int = SR) -> None:
    import soundfile as sf

    sf.write(str(path), audio, sr, subtype="FLOAT")


def read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    import soundfile as sf

    a, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return a, sr


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    fps: float
    frames: int
    duration: float


def video_info(path: str | Path) -> VideoInfo:
    """Size, frame rate and length. Remembered per file (and read again when the file changes): the app asks
    for it every second while a job runs."""
    p = Path(path)
    try:
        st = p.stat()
    except OSError as e:
        raise RuntimeError(f"Cannot open video {path}") from e
    return _video_info(str(p.resolve()), st.st_mtime_ns, st.st_size)


@functools.lru_cache(maxsize=64)
def _video_info(path: str, _mtime_ns: int, _size: int) -> VideoInfo:
    import cv2

    cap = cv2.VideoCapture(str(path))
    w = h = n = 0
    fps = 0.0
    if cap.isOpened():
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps, n = cap.get(cv2.CAP_PROP_FPS) or 0.0, int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    if not (w and h and n > 0):  # OpenCV can't read this file well: ask ffmpeg
        return _ffmpeg_info(path)
    if fps <= 0 or fps > 240:
        fps = 25.0
    return VideoInfo(w, h, fps, n, n / fps)


def _ffmpeg_info(path: str | Path) -> VideoInfo:
    import re

    err = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                         errors="replace").stderr
    size = re.search(r"Video: .*?(\d{2,5})x(\d{2,5})", err)
    if not size:
        raise RuntimeError(f"Cannot open video {path}")
    rate = re.search(r"([\d.]+) fps", err) or re.search(r"([\d.]+) tbr", err)
    dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    fps = float(rate.group(1)) if rate else 25.0
    fps = fps if 0 < fps <= 240 else 25.0
    seconds = int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3)) if dur else 0.0
    if not seconds:  # "Duration: N/A" (some WebM/MKV): read the video stream to its end to measure it
        run = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path), "-map", "0:v:0", "-c", "copy", "-f",
                              "null", "-"], capture_output=True, text=True, errors="replace").stderr
        times = re.findall(r"time=(\d+):(\d+):([\d.]+)", run)
        if times:
            hh, mm, ss = times[-1]
            seconds = int(hh) * 3600 + int(mm) * 60 + float(ss)
    w, h = int(size.group(1)), int(size.group(2))
    rot = re.search(r"rotation of (-?[\d.]+) degrees", err) or re.search(r"rotate\s*:\s*(-?\d+)", err)
    if rot and round(abs(float(rot.group(1)))) % 180 == 90:  # ffmpeg turns the picture upright: so do we
        w, h = h, w
    return VideoInfo(w, h, fps, int(seconds * fps), seconds)


def read_frames(path: str | Path, start: float, duration: float | None, fps: float, width: int, height: int,
                scale_flags: str = ""):
    """Yield BGR frames (writable numpy arrays) at a steady `fps` and the given size, decoded by ffmpeg.

    ffmpeg reads every format it knows (AV1, VP9, HEVC...); OpenCV's own decoder often can't. Stop ends it."""
    from . import jobs

    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-i", str(path)]
    if duration:
        cmd += ["-t", f"{duration:.3f}"]
    scale = f"scale={width}:{height}" + (f":flags={scale_flags}" if scale_flags else "")
    cmd += ["-an", "-sn", "-vf", f"fps={fps:.6f},{scale}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    size = width * height * 3
    proc = jobs.popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=size * 2)
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, np.uint8).reshape(height, width, 3).copy()
        jobs.check()  # frames ran out because Stop ended ffmpeg
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()
        jobs.done(proc)


def grab_frame(path: str | Path, t: float, width: int | None = None) -> tuple[np.ndarray | None, float]:
    """(BGR frame at `t` seconds, scale): optionally resized to `width`, decoded by ffmpeg. (None, 1.0) if none."""
    info = video_info(path)
    w = width or info.width
    h = max(2, round(info.height * w / info.width / 2) * 2)
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(path),
           "-frames:v", "1", "-an", "-sn", "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    out = subprocess.run(cmd, capture_output=True).stdout
    if len(out) < w * h * 3:
        return None, 1.0
    return np.frombuffer(out[: w * h * 3], np.uint8).reshape(h, w, 3).copy(), w / info.width


def fmt_time(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"
