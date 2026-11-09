"""Runs the whole process in two stages, reusing finished work from the project folder.

Stage 1 `prepare`  : audio -> remove Chinese voice -> Chinese transcript -> pick voices -> Khmer translation
                     (then the user can review/edit segments.json or the table in the app)
Stage 2 `produce`  : Khmer voice -> mix -> subtitles -> find text to blur -> final video
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from . import blur as blurmod
from .media import run_ffmpeg, video_info
from .project import Project, Segment, Settings
from .subtitles import read_srt, subtitle_lines, write_srt, write_zh_srt

Progress = Callable[[float, str], None]


class Pipeline:
    def __init__(self, project: Project, settings: Settings | None = None, api_key: str | None = None,
                 log: Callable[[str], None] = print, progress: Progress | None = None):
        self.p = project
        self.s = settings or project.load_settings()
        self.api_key = api_key
        self._log = log
        self._progress = progress
        self.p.save_settings(self.s)

    # ------------------------------------------------------------ helpers --
    def log(self, msg: str) -> None:
        self._log(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def stage(self, lo: float, hi: float) -> Progress:
        def f(frac: float, msg: str) -> None:
            if self._progress:
                self._progress(lo + (hi - lo) * max(0.0, min(1.0, frac)), msg)
        return f

    @property
    def original_wav(self) -> Path:
        return self.p.path("original.wav")

    @property
    def vocals_wav(self) -> Path:
        return self.p.path("vocals.wav")

    @property
    def music_wav(self) -> Path:
        return self.p.path("music.wav")

    # ------------------------------------------------------------ stage 1 --
    def extract_audio(self) -> None:
        if self.original_wav.exists():
            return
        self.log("Extracting audio")
        tmp = self.p.path("original.part.wav")
        try:
            run_ffmpeg(["-i", str(self.p.video), "-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(tmp)])
        except RuntimeError as e:
            raise RuntimeError("Could not extract audio. Does this video have sound?\n" + str(e)) from e
        tmp.replace(self.original_wav)

    def separate(self, progress: Progress) -> None:
        if self.music_wav.exists() and self.vocals_wav.exists():
            return
        from .separate import separate

        self.log("Removing the Chinese voice (Demucs). This is the slowest step on laptops without a GPU.")
        separate(self.original_wav, self.vocals_wav, self.music_wav, progress)

    def transcribe(self, progress: Progress, zh_srt: Path | None = None) -> list[Segment]:
        if zh_srt:
            self.log(f"Using Chinese subtitles from {Path(zh_srt).name}")
            return [Segment(id=i, start=a, end=b, zh=t) for i, (a, b, t) in enumerate(read_srt(zh_srt))]
        from .transcribe import transcribe

        src = self.vocals_wav if self.vocals_wav.exists() else self.original_wav
        segs = transcribe(src, self.s.whisper_model, progress, self.log)
        self.log(f"Chinese transcript: {len(segs)} lines")
        return segs

    def prepare(self, zh_srt: Path | None = None, km_srt: Path | None = None, retranslate: bool = False) -> list[Segment]:
        self.extract_audio()
        if self.s.remove_voice or self.s.voice_mode == "auto":
            self.separate(self.stage(0.0, 0.45))

        if km_srt:  # user already has Khmer subtitles: dub those directly
            self.log(f"Using Khmer subtitles from {Path(km_srt).name}")
            segs = [Segment(id=i, start=a, end=b, zh="", km=t) for i, (a, b, t) in enumerate(read_srt(km_srt))]
            self.p.save_segments(segs)
            self.p.path("voices_mode.txt").unlink(missing_ok=True)
        elif not self.p.has_segments():
            segs = self.transcribe(self.stage(0.45, 0.8), zh_srt)
            self.p.save_segments(segs)
            self.p.path("voices_mode.txt").unlink(missing_ok=True)
        segs = self.p.load_segments()

        marker = self.p.path("voices_mode.txt")
        if not marker.exists() or marker.read_text() != self.s.voice_mode:
            self.log("Choosing Sreymom/Piseth for each line" if self.s.voice_mode == "auto"
                     else f"Using {self.s.voice_mode} for every line")
            vocals = self.vocals_wav if self.vocals_wav.exists() else self.original_wav
            from .voices import assign_voices

            assign_voices(segs, vocals, self.s.voice_mode)
            marker.write_text(self.s.voice_mode)
            self.p.save_segments(segs)

        if retranslate:
            for s in segs:
                if s.zh:
                    s.km = ""
        from .translate import translate

        try:
            translate(segs, self.s.translator, self.s.translator_model, self.api_key,
                      self.stage(0.8, 1.0), self.log)
        finally:
            self.p.save_segments(segs)  # keep whatever got translated, even on error
        write_zh_srt(segs, self.p.path("chinese.srt"))
        if self._progress:
            self._progress(1.0, "Ready for review")
        return segs

    # ------------------------------------------------------------ stage 2 --
    def build_audio(self, progress: Progress) -> None:
        from .mix import mix
        from .tts import build_dub

        segs = self.p.load_segments()
        total = video_info(self.p.video).duration or _wav_seconds(self.original_wav)
        self.log("Generating Khmer voices (Sreymom / Piseth)")
        build_dub(segs, self.p.path("tts"), total, self.p.path("dub.wav"), self.p.path("timing.json"),
                  self.s.max_speedup, progress)
        voice_removed = self.s.remove_voice and self.music_wav.exists()
        bed = self.music_wav if voice_removed else self.original_wav
        self.log("Mixing Khmer voice with " + ("music/effects (Chinese voice removed)" if voice_removed
                                                else "the original sound (lowered under the dub)"))
        mix(bed, self.p.path("dub.wav"), self.p.path("mix.m4a"), voice_removed=voice_removed,
            background_volume=self.s.background_volume, dub_volume=self.s.dub_volume)

    def sub_lines(self):
        segs = self.p.load_segments()
        t = self.p.path("timing.json")
        timing = json.loads(t.read_text()) if t.exists() else None
        return subtitle_lines(segs, timing)

    def blur_timeline(self, progress: Progress, start: float = 0.0, end: float | None = None) -> blurmod.Timeline | None:
        info = video_info(self.p.video)
        tracks: list[dict] = []
        if self.s.blur in ("chinese", "all"):
            cache = self.p.path(f"blur_{self.s.blur}_{self.s.blur_sample_fps:g}fps.json")
            if cache.exists():
                tracks = blurmod.load_tracks(cache)
            elif start == 0.0 and end is None:
                self.log("Scanning the video for " + ("Chinese text" if self.s.blur == "chinese" else "text") + " to blur")
                tracks = blurmod.detect(self.p.video, self.s.blur, self.s.blur_sample_fps, progress=progress)
                blurmod.save_tracks(tracks, cache)
                self.log(f"Found {len(tracks)} pieces of text to blur")
            else:  # preview: scan only the preview range
                tracks = blurmod.detect(self.p.video, self.s.blur, self.s.blur_sample_fps, start, end, progress)
        tracks += blurmod.manual_tracks(self.s.blur_regions, info.width, info.height, info.duration)
        return blurmod.Timeline(tracks) if tracks else None

    def produce(self) -> Path:
        self.build_audio(self.stage(0.0, 0.35))
        lines = self.sub_lines()
        write_srt(lines, self.p.path(f"{self.p.video.stem}_khmer.srt"))
        timeline = self.blur_timeline(self.stage(0.35, 0.6))
        self.log("Making the final video")
        from .render import render

        out = render(self.p.video, self.p.path("mix.m4a"), self.p.output_video, self.p.dir,
                     lines if self.s.subtitles != "none" else None, self.s.subtitles, self.s.subtitle_size,
                     timeline, self.s.blur_style, self.s.video_quality,
                     progress=self.stage(0.6, 1.0), log=self.log)
        self.log(f"Done: {out}")
        return out

    def preview(self, start: float, seconds: float = 20.0) -> Path:
        """Short clip to check blur, subtitles and (if already made) the dub."""
        from .render import render

        audio = self.p.path("mix.m4a")
        if not audio.exists():
            self.extract_audio()
            audio = self.original_wav
        info = video_info(self.p.video)
        start = max(0.0, min(start, max(0.0, info.duration - 1)))
        seconds = min(seconds, info.duration - start)
        timeline = self.blur_timeline(self.stage(0.0, 0.5), start, start + seconds)
        lines = self.sub_lines() if self.p.has_segments() else None
        out = self.p.path("preview.mp4")
        render(self.p.video, audio, out, self.p.dir, lines if self.s.subtitles != "none" else None,
               "burn" if self.s.subtitles != "none" else "none", self.s.subtitle_size, timeline,
               self.s.blur_style, "fast", start, seconds, self.stage(0.5, 1.0), self.log)
        return out


def _wav_seconds(path: Path) -> float:
    import soundfile as sf

    return sf.info(str(path)).duration
