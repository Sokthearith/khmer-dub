"""Pick Sreymom (female) or Piseth (male) per line from the original speaker's pitch.

Uses a small YIN pitch estimator on the separated vocals. Typical speaking pitch is
~85-180 Hz for men and ~165-255 Hz for women; lines above the threshold get Sreymom.
Users can override any line in the review table.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .project import Segment

SR = 16000
FEMALE_THRESHOLD_HZ = 165.0


def _yin_frames(frames: np.ndarray, fmin=70.0, fmax=400.0, thresh=0.15) -> np.ndarray:
    """Vectorised YIN over frames (n, L). Returns f0 per frame (0 = unvoiced)."""
    n, L = frames.shape
    tmax = int(SR / fmin)
    W = L - tmax
    tmin = int(SR / fmax)
    x = frames - frames.mean(axis=1, keepdims=True)
    # autocorrelation between window [0, W) and shifted copies, via FFT
    nfft = 1 << int(np.ceil(np.log2(L + W)))
    X = np.fft.rfft(x, nfft)
    Wn = np.fft.rfft(x[:, :W], nfft)
    acf = np.fft.irfft(np.conj(Wn) * X, nfft)[:, : tmax + 1]
    sq = np.cumsum(np.pad(x**2, ((0, 0), (1, 0))), axis=1)
    e0 = sq[:, W] - sq[:, 0]
    taus = np.arange(tmax + 1)
    e_tau = sq[:, taus + W] - sq[:, taus]
    d = e0[:, None] + e_tau - 2 * acf
    d[:, 0] = 0
    cum = np.cumsum(d[:, 1:], axis=1) / np.arange(1, tmax + 1)
    cmnd = np.ones_like(d)
    cmnd[:, 1:] = d[:, 1:] / np.maximum(cum, 1e-12)
    f0 = np.zeros(n)
    for i in range(n):
        c = cmnd[i, tmin:]
        below = np.nonzero(c < thresh)[0]
        if below.size == 0:
            continue
        t = below[0]
        while t + 1 < c.size and c[t + 1] < c[t]:
            t += 1
        f0[i] = SR / (t + tmin)
    return f0


def segment_pitch(audio16k: np.ndarray, start: float, end: float, max_frames: int = 80) -> float:
    a = audio16k[int(start * SR): int(end * SR)]
    L, hop = int(0.05 * SR), int(0.01 * SR)
    if a.size < L:
        return 0.0
    idx = np.arange(0, a.size - L, hop)
    frames = np.stack([a[i:i + L] for i in idx])
    energy = (frames**2).mean(axis=1)
    loud = energy > max(energy.max() * 0.05, 1e-6)
    frames = frames[loud]
    if frames.shape[0] == 0:
        return 0.0
    if frames.shape[0] > max_frames:
        frames = frames[np.linspace(0, frames.shape[0] - 1, max_frames).astype(int)]
    f0 = _yin_frames(frames)
    f0 = f0[f0 > 0]
    return float(np.median(f0)) if f0.size >= 3 else 0.0


def pitch_threshold(pitches: list[float]) -> float:
    """Split point between the low (male) and high (female) voice groups of this video.

    Runs 2-means on log-pitch. If the video clearly has two groups (centres at least
    ~4 semitones apart, each with >= 10% of lines) the split is between them, kept
    within a plausible 130-230 Hz range; otherwise the textbook 165 Hz is used.
    """
    if len(pitches) < 4:
        return FEMALE_THRESHOLD_HZ
    x = np.log(np.array(pitches))
    lo, hi = np.percentile(x, 25), np.percentile(x, 75)
    for _ in range(20):
        mid = (lo + hi) / 2
        a, b = x[x < mid], x[x >= mid]
        if a.size == 0 or b.size == 0:
            return FEMALE_THRESHOLD_HZ
        lo, hi = a.mean(), b.mean()
    share = min(a.size, b.size) / x.size
    if hi - lo < np.log(1.26) or share < 0.1:
        return FEMALE_THRESHOLD_HZ
    return float(np.clip(np.exp((lo + hi) / 2), 130, 230))


def assign_voices(segs: list[Segment], vocals: Path, mode: str = "auto") -> None:
    """Set `pitch` (if unknown) and `voice` for each segment, in place."""
    if mode in ("sreymom", "piseth"):
        for s in segs:
            s.voice = mode
        return
    from .media import load_audio

    audio = load_audio(vocals, sr=SR, channels=1)[:, 0]
    for s in segs:
        if not s.pitch:
            s.pitch = round(segment_pitch(audio, s.start, s.end), 1)
    threshold = pitch_threshold([s.pitch for s in segs if s.pitch])
    # lines with unknown pitch inherit the neighbouring line's voice
    prev = "sreymom"
    for s in segs:
        if s.pitch:
            s.voice = "sreymom" if s.pitch >= threshold else "piseth"
            prev = s.voice
        else:
            s.voice = prev
