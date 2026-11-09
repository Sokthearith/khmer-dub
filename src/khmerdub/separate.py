"""Remove the Chinese voice: split the soundtrack into vocals + music/effects with Demucs.

Works chunk by chunk from a WAV on disk, so a 1-hour video doesn't need gigabytes of RAM.
music = original - vocals, which keeps every non-voice sound (music, effects, ambience).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np

from .devices import torch_device

CHUNK_SECONDS = 120
PAD_SECONDS = 4


def separate(
    original_wav: Path,
    vocals_out: Path,
    music_out: Path,
    progress: Callable[[float, str], None] | None = None,
    model_name: str = "htdemucs",
) -> None:
    import soundfile as sf
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    device = torch_device()
    model = get_model(model_name)
    model.eval()
    vocals_idx = model.sources.index("vocals")

    info = sf.info(str(original_wav))
    sr, total = info.samplerate, info.frames
    if sr != model.samplerate:
        raise ValueError(f"expected {model.samplerate} Hz audio, got {sr}")
    chunk, pad = CHUNK_SECONDS * sr, PAD_SECONDS * sr

    tmp_v, tmp_m = vocals_out.with_suffix(".part.wav"), music_out.with_suffix(".part.wav")
    with (
        sf.SoundFile(str(original_wav)) as src,
        sf.SoundFile(str(tmp_v), "w", sr, 2, subtype="PCM_16") as fv,
        sf.SoundFile(str(tmp_m), "w", sr, 2, subtype="PCM_16") as fm,
    ):
        for start in range(0, total, chunk):
            end = min(total, start + chunk)
            a, b = max(0, start - pad), min(total, end + pad)
            src.seek(a)
            mix = src.read(b - a, dtype="float32", always_2d=True)
            if mix.shape[1] == 1:
                mix = np.repeat(mix, 2, axis=1)
            mix = mix[:, :2]

            wav = torch.from_numpy(mix.T.copy())
            ref = wav.mean(0)
            mean, std = ref.mean(), ref.std() + 1e-8
            with torch.no_grad():
                out = apply_model(
                    model, ((wav - mean) / std)[None], device=device,
                    shifts=0, split=True, overlap=0.25, progress=False,
                )[0]
            vocals = (out[vocals_idx] * std + mean).cpu().numpy().T
            inner = slice(start - a, start - a + (end - start))
            v, m = vocals[inner], mix[inner] - vocals[inner]
            fv.write(np.clip(v, -1, 1))
            fm.write(np.clip(m, -1, 1))
            if progress:
                progress(end / total, f"Removing Chinese voice… {end / sr / 60:.0f}/{total / sr / 60:.0f} min")
    tmp_v.replace(vocals_out)
    tmp_m.replace(music_out)
