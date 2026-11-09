"""Khmer speech with Microsoft Edge neural voices (Sreymom / Piseth) + timing fit.

For each line:
  1. synthesise at normal speed (cached by text+voice+rate, so edits only redo that line)
  2. if it is longer than the time available before the next line, re-synthesise
     faster (edge-tts `rate`, sounds natural) up to `max_speedup`
  3. anything still too long is pushed later instead of overlapping the next line

Produces dub.wav (24 kHz mono) and timing.json (where each line actually landed,
used to time the Khmer subtitles).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from pathlib import Path
from typing import Callable

import numpy as np

from .media import load_audio, save_wav
from .project import VOICES, Segment

TTS_SR = 24000
CONCURRENCY = 6


def _clip_path(tts_dir: Path, text: str, voice: str, rate: int, pitch: int = 0) -> Path:
    key = f"{voice}|{rate}|{text}" if not pitch else f"{voice}|{rate}|{pitch}|{text}"
    return tts_dir / f"{hashlib.sha1(key.encode()).hexdigest()[:16]}.mp3"


def synth_line(tts_dir: Path, text: str, voice: str, rate: int = 0, pitch: int = 0) -> Path:
    """Make (or reuse) the Khmer audio for one line; used by the app's 'listen' button."""
    text = _clean_text(text)
    out = _clip_path(tts_dir, text, voice, rate, pitch)
    _synth_many([(text, voice, rate, pitch, out)], None, "")
    return out


async def _synth_one(sem, text: str, voice: str, rate: int, pitch: int, out: Path) -> None:
    import edge_tts

    if out.exists() and out.stat().st_size > 0:
        return
    async with sem:
        for attempt in range(5):
            try:
                tmp = out.with_suffix(".tmp")
                await edge_tts.Communicate(text, VOICES[voice], rate=f"{rate:+d}%", pitch=f"{pitch:+d}Hz").save(str(tmp))
                tmp.replace(out)
                return
            except Exception:
                if attempt == 4:
                    raise
                await asyncio.sleep(2 * (attempt + 1))


def _synth_many(jobs: list[tuple[str, str, int, int, Path]], progress, label: str) -> None:
    async def main():
        sem = asyncio.Semaphore(CONCURRENCY)
        tasks = [asyncio.create_task(_synth_one(sem, *j)) for j in jobs]
        for i, t in enumerate(asyncio.as_completed(tasks), 1):
            await t
            if progress:
                progress(i / len(tasks), f"{label} {i}/{len(tasks)}")

    if jobs:
        asyncio.run(main())


def _load_trimmed(path: Path) -> np.ndarray:
    a = load_audio(path, sr=TTS_SR, channels=1)[:, 0]
    loud = np.nonzero(np.abs(a) > 0.01)[0]
    if loud.size == 0:
        return a[:0]
    pad = int(0.03 * TTS_SR)
    return a[max(0, loud[0] - pad): loud[-1] + pad]


def _clean_text(t: str) -> str:
    return " ".join(t.replace("​", " ").split())


def build_dub(
    segs: list[Segment],
    tts_dir: Path,
    total_seconds: float,
    dub_wav: Path,
    timing_json: Path,
    max_speedup: float = 1.5,
    progress: Callable[[float, str], None] | None = None,
    speed: int = 0,
    pitch: int = 0,
) -> None:
    tts_dir.mkdir(parents=True, exist_ok=True)
    lines = [s for s in segs if _clean_text(s.km)]
    lines.sort(key=lambda s: s.start)

    # time available for each line = until the next line starts (or video end)
    avail = {}
    for i, s in enumerate(lines):
        nxt = lines[i + 1].start if i + 1 < len(lines) else total_seconds
        avail[s.id] = max(s.duration, nxt - s.start) * 0.97

    # pass 1: chosen speed
    p1 = lambda f, m: progress(f * 0.6, m) if progress else None  # noqa: E731
    _synth_many([(_clean_text(s.km), s.voice, speed, pitch, _clip_path(tts_dir, _clean_text(s.km), s.voice, speed, pitch))
                 for s in lines], p1, "Khmer voice: line")

    clips: dict[int, np.ndarray] = {}
    rates: dict[int, int] = {}
    redo = []
    for s in lines:
        text = _clean_text(s.km)
        a = _load_trimmed(_clip_path(tts_dir, text, s.voice, speed, pitch))
        ratio = (a.size / TTS_SR) / avail[s.id] if avail[s.id] > 0 else 1
        if ratio > 1.02:
            # edge-tts rate is relative to normal speed: combine the base speed with the extra needed
            need = (1 + speed / 100) * ratio
            rate = min(int(math.ceil((need - 1) * 100)) + 3, int((max_speedup - 1) * 100) + max(speed, 0))
            if rate > speed:
                rates[s.id] = rate
                redo.append((text, s.voice, rate, pitch, _clip_path(tts_dir, text, s.voice, rate, pitch)))
        clips[s.id] = a

    # pass 2: faster versions for lines that don't fit
    p2 = lambda f, m: progress(0.6 + f * 0.3, m) if progress else None  # noqa: E731
    _synth_many(redo, p2, "Khmer voice: speeding up line")
    for s in lines:
        if s.id in rates:
            clips[s.id] = _load_trimmed(_clip_path(tts_dir, _clean_text(s.km), s.voice, rates[s.id], pitch))

    # place clips on the timeline
    n = int(math.ceil(total_seconds * TTS_SR)) + TTS_SR
    track = np.zeros(n, dtype=np.float32)
    cursor = 0.0
    timing = {}
    for s in lines:
        a = clips[s.id]
        start = max(s.start, cursor)
        i0 = int(start * TTS_SR)
        i1 = min(n, i0 + a.size)
        if i1 > i0:
            track[i0:i1] += a[: i1 - i0]
        end = start + a.size / TTS_SR
        cursor = end + 0.08
        # subtitle shows while the Khmer voice speaks (and at least as long as the original line if on time)
        sub_end = max(end, s.end) if start == s.start else end
        timing[s.id] = {"start": round(start, 3), "end": round(sub_end, 3), "rate": rates.get(s.id, speed)}
    peak = float(np.abs(track).max()) if track.size else 0
    if peak > 0.98:
        track *= 0.98 / peak
    save_wav(dub_wav, track[: int(total_seconds * TTS_SR) or n], TTS_SR)
    timing_json.write_text(json.dumps(timing), encoding="utf-8")
    if progress:
        progress(1.0, "Khmer voice done")
