"""Mix the Khmer dub over the background (music/effects with the Chinese voice removed).

All mixing is done by ffmpeg in streaming mode, so a 1-hour video needs little RAM.
If voice removal is off, the original soundtrack is automatically lowered
("ducked") whenever the Khmer voice speaks.
"""

from __future__ import annotations

from pathlib import Path

from .media import run_ffmpeg


def mix(bed: Path, dub_wav: Path, out_m4a: Path, *, voice_removed: bool,
        background_volume: float = 1.0, dub_volume: float = 1.0) -> None:
    dub = f"[1:a]aresample=44100,volume={dub_volume:.3f},pan=stereo|c0=c0|c1=c0[d]"
    bed_f = f"[0:a]aresample=44100,aformat=channel_layouts=stereo,volume={background_volume:.3f}[b]"
    if voice_removed:
        graph = f"{bed_f};{dub};[b][d]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[out]"
    else:
        graph = (
            f"{bed_f};{dub};[d]asplit[d1][d2];"
            "[b][d1]sidechaincompress=threshold=0.02:ratio=12:attack=15:release=400[ducked];"
            "[ducked][d2]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[out]"
        )
    run_ffmpeg([
        "-i", str(bed), "-i", str(dub_wav), "-filter_complex", graph,
        "-map", "[out]", "-c:a", "aac", "-b:a", "192k", str(out_m4a),
    ])
