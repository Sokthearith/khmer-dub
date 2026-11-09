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
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args]
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd)}\n{p.stderr[-3000:]}")


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


@dataclass
class VideoInfo:
    width: int
    height: int
    fps: float
    frames: int
    duration: float


def video_info(path: str | Path) -> VideoInfo:
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video {path}")
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    if fps <= 0 or fps > 240:
        fps = 25.0
    return VideoInfo(w, h, fps, n, n / fps if n > 0 else 0.0)


def fmt_time(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"
