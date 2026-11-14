"""Chinese speech -> timed Chinese transcript with faster-whisper."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from .devices import prepare_cuda_for_ctranslate2
from .project import Segment

# Phrases Whisper tends to invent on music/silence in Chinese audio.
HALLUCINATIONS = ("明镜", "点点栏目", "Amara", "字幕由", "字幕提供", "请不吝点赞", "订阅我的频道", "字幕志愿者")
SPLIT_PUNCT = "。！？!?；;，,…"
MAX_SEG = 6.0  # seconds; longer lines are split so the dub stays in sync


def pick_model(name: str) -> tuple[str, str, str]:
    """Return (model, device, compute_type)."""
    gpu = prepare_cuda_for_ctranslate2()
    if name in ("", "auto"):
        name = "large-v3-turbo" if gpu else "medium"
    return name, ("cuda" if gpu else "cpu"), ("float16" if gpu else "int8")


SMALL_PUNCT = str.maketrans({"﹔": "；", "﹐": "，", "﹑": "、", "﹒": "。", "﹖": "？", "﹗": "！"})


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(SMALL_PUNCT)).strip()


def _split_long(seg, words) -> list[tuple[float, float, str]]:
    """Split a long Whisper segment into shorter lines at punctuation / pauses."""
    if seg.end - seg.start <= MAX_SEG or not words:
        return [(seg.start, seg.end, _clean(seg.text))]
    pieces, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        dur = cur[-1].end - cur[0].start
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt.start - w.end) if nxt else 0
        punct = w.word.strip()[-1:] in SPLIT_PUNCT if w.word.strip() else False
        if nxt is None or (dur > 1.5 and (punct or gap > 0.4)) or dur > MAX_SEG:
            pieces.append((cur[0].start, cur[-1].end, _clean("".join(x.word for x in cur))))
            cur = []
    return [p for p in pieces if p[2]]


def transcribe(
    audio: Path,
    model_name: str = "auto",
    progress: Callable[[float, str], None] | None = None,
    log: Callable[[str], None] = print,
) -> list[Segment]:
    from faster_whisper import WhisperModel

    name, device, compute = pick_model(model_name)
    log(f"Whisper model: {name} on {device} ({compute}). First run downloads the model.")
    try:
        model = WhisperModel(name, device=device, compute_type=compute)
    except Exception as e:
        if device == "cpu":
            raise
        log(f"GPU failed for Whisper ({e}); using CPU instead.")
        name, device, compute = pick_model("medium" if model_name == "auto" else model_name)[0], "cpu", "int8"
        model = WhisperModel(name, device=device, compute_type=compute)

    from .media import load_audio

    samples = load_audio(audio, sr=16000, channels=1)[:, 0]  # decode with ffmpeg, not PyAV
    total = samples.size / 16000
    # On a CPU a narrower search is ~15% faster and gives almost the same text (98% the same in tests)
    opts = dict(language="zh", beam_size=5 if device == "cuda" else 3, word_timestamps=True,
                condition_on_previous_text=False,
                initial_prompt="以下是普通话电视剧的对白，使用简体中文。")
    seg_iter, info = model.transcribe(
        samples, vad_filter=True, vad_parameters={"min_silence_duration_ms": 400, "speech_pad_ms": 200}, **opts)
    raw = []
    for seg in seg_iter:
        raw.append(seg)
        if progress and info.duration:
            progress(min(1.0, seg.end / info.duration),
                     f"Chinese transcript… {seg.end / 60:.0f}/{info.duration / 60:.0f} min")

    lines: list[tuple[float, float, str]] = []
    for i, seg in enumerate(raw):
        if not _is_made_up(seg.text):
            lines += _split_long(seg, seg.words or [])
            continue
        # Whisper invented a stock phrase here, usually over real speech it then skipped:
        # listen to that stretch again on its own (up to the next real line) and keep what is real.
        nxt = next((r.start for r in raw[i + 1:] if not _is_made_up(r.text)), None)
        a, b = seg.start, min(nxt if nxt is not None else total, seg.start + 30.0, total)
        if b - a < 0.8:
            continue
        for c0, c1 in _speech_parts(samples, a, b):  # each spoken part on its own: Whisper skips less
            again, _ = model.transcribe(samples[int(c0 * 16000): int(c1 * 16000)], vad_filter=False, **opts)
            for r in again:
                if not _is_made_up(r.text):
                    lines += [(c0 + s, c0 + e, t) for s, e, t in _split_long(r, r.words or [])]
        log(f"Listened again to {a:.0f}–{b:.0f} s (speech recognition had made up a line there)")

    out: list[Segment] = []
    for start, end, text in sorted(lines):
        if any(ch.isalnum() for ch in text) and not _is_made_up(text):  # skip lines with no words ("、")
            out.append(Segment(id=len(out), start=round(start, 3), end=round(end, 3), zh=text))
    return out


def _speech_parts(samples, a: float, b: float) -> list[tuple[float, float]]:
    """The spoken stretches between pauses inside [a, b] seconds (or the whole range if that fails)."""
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        ts = get_speech_timestamps(samples[int(a * 16000): int(b * 16000)],
                                   VadOptions(min_silence_duration_ms=300, speech_pad_ms=150))
    except Exception:
        return [(a, b)]
    parts: list[list[float]] = []
    for t in ts:
        s0, s1 = a + t["start"] / 16000, a + t["end"] / 16000
        if parts and s0 - parts[-1][1] < 0.3:
            parts[-1][1] = s1
        else:
            parts.append([s0, s1])
    return [(s0, s1) for s0, s1 in parts if s1 - s0 >= 0.4] or [(a, b)]


def _is_made_up(text: str) -> bool:
    return any(h in text for h in HALLUCINATIONS)
