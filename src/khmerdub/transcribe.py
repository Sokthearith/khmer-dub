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


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


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
    seg_iter, info = model.transcribe(
        samples,
        language="zh",
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400, "speech_pad_ms": 200},
        word_timestamps=True,
        condition_on_previous_text=False,
        initial_prompt="以下是普通话电视剧的对白，使用简体中文。",
    )
    out: list[Segment] = []
    for seg in seg_iter:
        for start, end, text in _split_long(seg, seg.words or []):
            if not text or any(h in text for h in HALLUCINATIONS):
                continue
            out.append(Segment(id=len(out), start=round(start, 3), end=round(end, 3), zh=text))
        if progress and info.duration:
            progress(min(1.0, seg.end / info.duration),
                     f"Chinese transcript… {seg.end / 60:.0f}/{info.duration / 60:.0f} min")
    return out
