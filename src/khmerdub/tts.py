"""Khmer speech with Microsoft Edge neural voices (Sreymom / Piseth), timed to the characters.

For each line (fit mode "match", the default):
  1. synthesise at the chosen speed (cached by text+voice+rate+pitch, so edits only redo that line)
  2. compare its length with how long the character actually speaks, and re-synthesise slower
     (down to 0.85x) or faster (up to max_speedup) so the Khmer voice starts AND ends with them
  3. if a line still doesn't fit before the next one, it is pushed later instead of overlapping

Fit mode "natural" only speeds a line up when it would run into the next one.
Per line, `offset` moves the voice earlier/later and `rate` fixes its speed by hand.

Produces dub.wav (24 kHz mono) and timing.json: where each line landed, its speed and a fit verdict
(ok / fast / late / long / short) that the app shows so lines needing attention are easy to find.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from .media import load_audio, save_wav
from .project import VOICES, Segment

TTS_SR = 24000
CONCURRENCY = 4  # at the same time; more makes the free voice service refuse more often
SLOWEST = 15  # % slower than the chosen speed, at most, to stretch a short line
LATE, OFF_END = 0.15, 0.35  # seconds: what counts as "late" / ending clearly early or late


VOICE_BUSY = ("The Khmer voice service (Microsoft) did not answer for many lines, even after waiting. It is "
              "probably busy or the internet dropped. Wait a few minutes and press the button again: lines "
              "already made are kept.")


class VoiceFailed(Exception):
    """The voice service gave no audio for one line, even after retries."""


def _clean_text(t: str) -> str:
    return " ".join(t.replace("​", " ").split())


def speakable(t: str) -> bool:
    """Has something to say aloud (a letter or number), not only "..." or "!?" (the service refuses those)."""
    return any(ch.isalnum() for ch in t)


def _clip_path(tts_dir: Path, text: str, voice: str, rate: int, pitch: int = 0) -> Path:
    key = f"{voice}|{rate}|{text}" if not pitch else f"{voice}|{rate}|{pitch}|{text}"
    return tts_dir / f"{hashlib.sha1(key.encode()).hexdigest()[:16]}.mp3"


def line_key(s: Segment) -> str:
    """Changes when anything that affects this line's voice or timing changes."""
    return hashlib.sha1(f"{_clean_text(s.km)}|{s.voice}|{s.offset:.2f}|{s.rate}|{s.start:.2f}|{s.end:.2f}"
                        .encode()).hexdigest()[:10]


def synth_line(tts_dir: Path, text: str, voice: str, rate: int = 0, pitch: int = 0) -> Path:
    """Make (or reuse) the Khmer audio for one line; used by the app's 'listen' button."""
    text = _clean_text(text)
    if not speakable(text):
        raise RuntimeError("This line has nothing to say aloud (only punctuation), so it stays silent.")
    out = _clip_path(tts_dir, text, voice, rate, pitch)
    if _synth_many([(text, voice, rate, pitch, out)], None, ""):
        raise RuntimeError(VOICE_BUSY)
    return out


async def _synth_one(sem, text: str, voice: str, rate: int, pitch: int, out: Path) -> None:
    import edge_tts

    if out.exists() and out.stat().st_size > 0:
        return
    async with sem:
        tries = 8  # the free voice service sometimes refuses for a minute when busy: wait it out (~2 min)
        for attempt in range(tries):
            try:
                tmp = out.with_suffix(".tmp")
                await edge_tts.Communicate(text, VOICES[voice], rate=f"{rate:+d}%", pitch=f"{pitch:+d}Hz").save(str(tmp))
                tmp.replace(out)
                return
            except Exception as e:
                if attempt == tries - 1:
                    raise VoiceFailed(type(e).__name__) from e
                await asyncio.sleep(min(30.0, 2.0 ** attempt) + random.random())


def _synth_many(jobs: list[tuple[str, str, int, int, Path]], progress, label: str) -> set[Path]:
    """Make the clips; returns the ones the voice service would not give (so one bad line can't sink a video)."""
    jobs = list({j[4]: j for j in jobs}.values())  # same clip once
    failed: set[Path] = set()

    async def one(sem, j):
        try:
            await _synth_one(sem, *j)
        except VoiceFailed:
            failed.add(j[4])

    async def main():
        sem = asyncio.Semaphore(CONCURRENCY)
        tasks = [asyncio.create_task(one(sem, j)) for j in jobs]
        for i, t in enumerate(asyncio.as_completed(tasks), 1):
            await t
            if progress:
                progress(i / len(tasks), f"{label} {i}/{len(tasks)}")

    if jobs:
        asyncio.run(main())
    return failed


def decode(path: Path) -> np.ndarray:
    """Mono 24 kHz samples with the silence at both ends trimmed."""
    try:
        import soundfile as sf

        a, sr = sf.read(str(path), dtype="float32", always_2d=True)
        a = a.mean(axis=1)
        if sr != TTS_SR:
            raise ValueError("resample")
    except Exception:
        a = load_audio(path, sr=TTS_SR, channels=1)[:, 0]
    loud = np.nonzero(np.abs(a) > 0.01)[0]
    if loud.size == 0:
        return a[:0]
    pad = int(0.03 * TTS_SR)
    return a[max(0, loud[0] - pad): loud[-1] + pad]


@dataclass
class Placed:
    start: float
    end: float
    rate: int
    status: str  # ok | fast | late | long | short | silent (nothing to say) | novoice (the service gave none)
    late: float = 0.0
    off: float = 0.0  # + ends after the character stops, - ends before
    key: str = ""


def _rate_for(length: float, target: float, base: int, max_speedup: float, stretch: bool) -> int:
    """Speaking rate (%) that makes a clip measured at `base` last about `target` seconds."""
    if target <= 0 or length <= 0:
        return base
    need = (1 + base / 100) * length / target  # speed factor vs normal
    hi = 1 + ((max_speedup - 1) * 100 + max(base, 0)) / 100
    lo = (1 + (base - SLOWEST) / 100) if stretch else (1 + base / 100)
    rate = round((min(max(need, lo), hi) - 1) * 100)
    return base if abs(rate - base) <= 3 else rate  # close enough: keep the natural speed


def plan(lines: list[Segment], tts_dir: Path, total: float, base: int = 0, pitch: int = 0,
         max_speedup: float = 1.5, mode: str = "match",
         progress: Callable[[float, str], None] | None = None) -> tuple[dict[int, np.ndarray], dict[int, Placed]]:
    """Make the voices for `lines` (sorted, with Khmer text) and decide where each one goes."""
    tts_dir.mkdir(parents=True, exist_ok=True)
    text = {s.id: _clean_text(s.km) for s in lines}
    first_rate = {s.id: (s.rate if s.rate is not None else base) for s in lines}
    clip = lambda s, r: _clip_path(tts_dir, text[s.id], s.voice, r, pitch)  # noqa: E731

    silent = {s.id for s in lines if not speakable(text[s.id])}  # "..." and the like: subtitle only
    talk = [s for s in lines if s.id not in silent]
    p1 = (lambda f, m: progress(f * 0.6, m)) if progress else None
    failed = _synth_many([(text[s.id], s.voice, first_rate[s.id], pitch, clip(s, first_rate[s.id])) for s in talk],
                         p1, "Khmer voice: line")
    novoice = {s.id for s in talk if clip(s, first_rate[s.id]) in failed}
    if len(novoice) > max(3, len(talk) // 20):  # not a few unlucky lines: the service is down
        raise RuntimeError(VOICE_BUSY)
    quiet = silent | novoice

    starts = [max(0.0, s.start + s.offset) for s in lines]
    rates, redo = {}, []
    for i, s in enumerate(lines):
        if s.id in quiet:
            rates[s.id] = first_rate[s.id]
            continue
        if s.rate is not None:
            rates[s.id] = s.rate
            continue
        length = decode(_clip_path(tts_dir, text[s.id], s.voice, base, pitch)).size / TTS_SR
        nxt = starts[i + 1] if i + 1 < len(lines) else total
        room = max(0.3, nxt - starts[i] - 0.05)
        target = min(max(s.duration, 0.3), room) if mode == "match" else room
        stretch = mode == "match"
        if mode != "match" and length <= room:
            rates[s.id] = base
            continue
        r = _rate_for(length, target, base, max_speedup, stretch)
        rates[s.id] = r
        if r != base:
            redo.append((text[s.id], s.voice, r, pitch, _clip_path(tts_dir, text[s.id], s.voice, r, pitch)))

    p2 = (lambda f, m: progress(0.6 + f * 0.3, m)) if progress else None
    failed = _synth_many(redo, p2, "Khmer voice: fitting line")
    for s in lines:  # a faster/slower take the service would not give: keep the normal one
        if s.id not in quiet and clip(s, rates[s.id]) in failed:
            rates[s.id] = first_rate[s.id]

    clips, placed, cursor = {}, {}, 0.0
    for i, s in enumerate(lines):
        if s.id in quiet:  # no voice: the subtitle keeps the original timing, nothing is pushed
            clips[s.id] = np.zeros(0, dtype=np.float32)
            placed[s.id] = Placed(round(starts[i], 3), round(max(starts[i], s.end + s.offset), 3), rates[s.id],
                                  "silent" if s.id in silent else "novoice", 0.0, 0.0, line_key(s))
            continue
        a = decode(_clip_path(tts_dir, text[s.id], s.voice, rates[s.id], pitch))
        clips[s.id] = a
        start = max(starts[i], cursor)
        end = start + a.size / TTS_SR
        cursor = end + 0.08
        late = start - starts[i]
        off = end - (s.end + s.offset)
        if late > LATE:
            status = "late"
        elif mode == "match" and off > OFF_END:
            status = "long"
        elif mode == "match" and off < -OFF_END:
            status = "short"
        elif rates[s.id] - base >= 20:
            status = "fast"
        else:
            status = "ok"
        placed[s.id] = Placed(round(start, 3), round(end, 3), rates[s.id], status, round(late, 2), round(off, 2),
                              line_key(s))
    return clips, placed


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
    mode: str = "match",
    meta: dict | None = None,
) -> dict[int, Placed]:
    lines = sorted((s for s in segs if _clean_text(s.km)), key=lambda s: s.start + s.offset)
    clips, placed = plan(lines, tts_dir, total_seconds, speed, pitch, max_speedup, mode, progress)

    n = int(math.ceil(total_seconds * TTS_SR)) + TTS_SR
    track = np.zeros(n, dtype=np.float32)
    timing = {}
    for s in lines:
        a, pl = clips[s.id], placed[s.id]
        i0 = int(pl.start * TTS_SR)
        i1 = min(n, i0 + a.size)
        if i1 > i0:
            track[i0:i1] += a[: i1 - i0]
        # the subtitle shows while the Khmer voice speaks, and at least as long as the original line when on time
        sub_end = max(pl.end, s.end + s.offset) if pl.late <= LATE else pl.end
        timing[s.id] = {**asdict(pl), "sub_end": round(sub_end, 3)}
    peak = float(np.abs(track).max()) if track.size else 0
    if peak > 0.98:
        track *= 0.98 / peak
    save_wav(dub_wav, track[: int(total_seconds * TTS_SR) or n], TTS_SR)
    if meta:
        timing["_settings"] = meta  # lets the review page tell when the overall voice settings changed
    timing_json.write_text(json.dumps(timing), encoding="utf-8")
    if progress:
        progress(1.0, "Khmer voice done")
    return placed
