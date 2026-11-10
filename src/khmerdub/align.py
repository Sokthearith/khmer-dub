"""Sharpen each line's start and end to when the character's voice really starts and stops.

Whisper's timestamps are often 0.2-1 s off (line ends especially come early). We look at the loudness of the
separated Chinese voice (vocals.wav) around each line and move the start/end to the first/last moment of
real speech, within safe limits and without running into the neighbouring lines.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .project import Segment

SR, HOP = 16000, 0.02  # 20 ms loudness frames


def _frames(audio: np.ndarray) -> np.ndarray:
    step = int(SR * HOP)
    n = audio.size // step
    return np.sqrt((audio[: n * step].reshape(n, step) ** 2).mean(axis=1))


def refine_bounds(segs: list[Segment], vocals: Path) -> int:
    """Adjust start/end of each segment in place. Returns how many were changed."""
    from .media import load_audio

    rms = _frames(load_audio(vocals, sr=SR, channels=1)[:, 0])
    segs.sort(key=lambda s: s.start)
    changed = 0
    prev_end = 0.0
    for i, s in enumerate(segs):
        nxt = segs[i + 1].start if i + 1 < len(segs) else s.end + 1.0
        lo = max(prev_end + 0.02, s.start - 0.35)
        hi = min(nxt - 0.02, s.end + 0.6)
        f0, f1 = int(lo / HOP), min(int(hi / HOP), rms.size)
        inner = rms[int(s.start / HOP): int(s.end / HOP)]
        if f1 - f0 < 10 or inner.size < 5:
            prev_end = s.end
            continue
        level = float(np.percentile(inner, 90))
        floor = float(np.percentile(rms[f0:f1], 10))
        if level < 1e-3 or level < floor * 3:  # too quiet / too noisy to judge: leave as is
            prev_end = s.end
            continue
        voiced = rms[f0:f1] > max(level * 0.12, floor * 2.5)
        runs = np.convolve(voiced.astype(int), np.ones(3, dtype=int), "same") >= 3  # ignore single blips
        idx = np.nonzero(runs)[0]
        if idx.size == 0:
            prev_end = s.end
            continue
        new_start = (f0 + idx[0] - 1) * HOP - 0.04
        new_end = (f0 + idx[-1] + 2) * HOP + 0.06
        new_start = min(max(new_start, s.start - 0.35, lo), s.start + 0.4)
        new_end = max(min(new_end, s.end + 0.6, hi), s.end - 0.5)
        if new_end - new_start >= 0.3 and (abs(new_start - s.start) > 0.03 or abs(new_end - s.end) > 0.03):
            s.start, s.end = round(new_start, 3), round(new_end, 3)
            changed += 1
        prev_end = s.end
    return changed
