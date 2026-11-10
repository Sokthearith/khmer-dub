"""Runs the whole process in two stages, reusing finished work from the project folder.

Stage 1 `prepare`  : audio -> remove Chinese voice -> Chinese transcript -> pick voices -> Khmer translation
                     (then the user can review/edit segments.json or the table in the app)
Stage 2 `produce`  : Khmer voice -> mix -> subtitles -> find text to blur -> final video
"""

from __future__ import annotations

import json
import shutil
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

        # a subtitle file is imported once (or again when its content changes), so Start again keeps your edits
        new_km = bool(km_srt) and (self._new_srt(km_srt) or not self.p.has_segments())
        new_zh = bool(zh_srt) and not km_srt and self._new_srt(zh_srt)
        if new_km:  # user already has Khmer subtitles: dub those directly
            self.log(f"Using Khmer subtitles from {Path(km_srt).name}")
            segs = [Segment(id=i, start=a, end=b, zh="", km=t) for i, (a, b, t) in enumerate(read_srt(km_srt))]
            self.p.save_segments(segs)
            self.p.path("voices_mode.txt").unlink(missing_ok=True)
            self.p.path("bounds_refined.txt").unlink(missing_ok=True)
        elif not self.p.has_segments() or new_zh:
            segs = self.transcribe(self.stage(0.45, 0.8), zh_srt)
            if not segs:
                raise RuntimeError(
                    "No Chinese speech was found in this video, so there is nothing to dub. If it does have speech, "
                    "set Speech recognition to large-v3 in Settings (More options), or add a Chinese .srt file.")
            self.p.save_segments(segs)
            self.p.path("voices_mode.txt").unlink(missing_ok=True)
            self.p.path("bounds_refined.txt").unlink(missing_ok=True)
        self.refine_bounds()
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
                      self.stage(0.8, 1.0), self.log, self.s.translator_provider, self.s.translator_base_url)
        finally:
            self.p.save_segments(segs)  # keep whatever got translated, even on error
        write_zh_srt(segs, self.p.path("chinese.srt"))
        if self._progress:
            self._progress(1.0, "Ready for review")
        return segs

    # ------------------------------------------------------------ stage 2 --
    def _new_srt(self, path) -> bool:
        """True the first time a given subtitle file is used, so pressing Start again keeps your edits."""
        import hashlib

        digest = hashlib.sha1(Path(path).read_bytes()).hexdigest()
        marker = self.p.path("imported_srt.txt")
        if marker.exists() and marker.read_text().strip() == digest:
            return False
        marker.write_text(digest)
        return True

    def refine_bounds(self) -> None:
        """Once per transcript: snap each line to when the character's voice really starts and stops."""
        marker = self.p.path("bounds_refined.txt")
        if marker.exists() or not self.vocals_wav.exists() or not self.p.has_segments():
            return
        from .align import refine_bounds

        segs = self.p.load_segments()
        n = refine_bounds(segs, self.vocals_wav)
        self.p.save_segments(segs)
        marker.write_text(str(n))
        self.log(f"Matched {n} lines to the exact moments the characters speak")

    def build_audio(self, progress: Progress) -> None:
        from .mix import mix
        from .tts import build_dub

        if self.s.remove_voice and not self.music_wav.exists():  # voice removal switched on after Start
            self.extract_audio()
            self.separate(progress)
        self.refine_bounds()
        segs = self.p.load_segments()
        total = video_info(self.p.video).duration or _wav_seconds(self.original_wav)
        self.log("Generating Khmer voices (Sreymom / Piseth)")
        build_dub(segs, self.p.path("tts"), total, self.p.path("dub.wav"), self.p.path("timing.json"),
                  self.s.max_speedup, progress, int(self.s.voice_speed), int(self.s.voice_pitch), self.s.fit_mode,
                  meta=self._voice_settings())
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

    @property
    def blur_cache(self) -> Path:
        return self.p.path(f"blur_{self.s.blur}_{self.s.blur_sample_fps:g}fps.json")

    def scan_text(self, progress: Progress | None = None) -> list[dict]:
        """Run (or reuse) the automatic text scan for the whole video."""
        if self.s.blur not in ("chinese", "all"):
            return []
        if not self.blur_cache.exists():
            self.log("Scanning the video for " + ("Chinese text" if self.s.blur == "chinese" else "text") + " to blur")
            tracks = blurmod.detect(self.p.video, self.s.blur, self.s.blur_sample_fps,
                                    progress=progress or self.stage(0, 1))
            blurmod.save_tracks(tracks, self.blur_cache)
            self.log(f"Found {len(tracks)} pieces of text to blur")
        return blurmod.load_tracks(self.blur_cache)

    def blur_timeline(self, progress: Progress, start: float = 0.0, end: float | None = None) -> blurmod.Timeline | None:
        info = video_info(self.p.video)
        tracks: list[dict] = []
        if self.s.blur in ("chinese", "all"):
            cache = self.blur_cache
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
                     timeline, self.s.blur_style, self.s.video_quality, self.s.resolution,
                     self.original_wav if self.s.keep_original_audio else None, self.sub_style(),
                     progress=self.stage(0.6, 1.0), log=self.log)
        shutil.copy(self.p.path("mix.m4a"), self.p.path(f"{self.p.video.stem}_khmer_audio.m4a"))
        self.log(f"Done: {out}")
        return out

    def run_all(self, zh_srt: Path | None = None, km_srt: Path | None = None) -> Path:
        """Everything without stopping for review."""
        progress = self._progress
        self._progress = (lambda f, m: progress(f * 0.5, m)) if progress else None
        self.prepare(zh_srt, km_srt)
        self._progress = (lambda f, m: progress(0.5 + f * 0.5, m)) if progress else None
        try:
            return self.produce()
        finally:
            self._progress = progress

    def sub_style(self) -> dict:
        return {"position": self.s.subtitle_position, "color": self.s.subtitle_color, "box": self.s.subtitle_box}

    def downloads(self) -> list[Path]:
        stem = self.p.video.stem
        names = [self.p.output_video.name, f"{stem}_khmer.srt", f"{stem}_khmer_audio.m4a", "chinese.srt"]
        return [self.p.path(n) for n in names if self.p.path(n).exists()]

    # ---------------------------------------------------------- per line --
    def line_original_audio(self, seg: Segment) -> Path:
        """Short clip of the original line (Chinese voice) to listen to while reviewing."""
        self.extract_audio()
        clips = self.p.path("clips")
        clips.mkdir(exist_ok=True)
        out = clips / f"zh_{seg.id}_{seg.start:.2f}_{seg.end:.2f}.m4a"
        if not out.exists():
            a = max(0.0, seg.start - 0.25)
            run_ffmpeg(["-ss", f"{a:.3f}", "-t", f"{seg.end + 0.25 - a:.3f}", "-i", str(self.original_wav),
                        "-c:a", "aac", "-b:a", "96k", str(out)])
        return out

    def line_khmer_audio(self, text: str, voice: str, rate: int | None = None) -> Path:
        from .tts import synth_line

        r = int(self.s.voice_speed) if rate is None else int(rate)
        return synth_line(self.p.path("tts"), text, voice, r, int(self.s.voice_pitch))

    # ---------------------------------------------------------- sync check --
    def fit_report(self) -> dict:
        """Per line: how its Khmer voice fits the character (from the last 'make voices'), plus counts.

        Lines edited since then are 'changed' until the voices are made again."""
        from .tts import line_key

        t = self.p.path("timing.json")
        timing = json.loads(t.read_text()) if t.exists() else {}
        segs = self.p.load_segments() if self.p.has_segments() else []
        lines, counts = {}, {"ok": 0, "fast": 0, "late": 0, "long": 0, "short": 0, "changed": 0, "none": 0}
        base = int(self.s.voice_speed)
        # the overall speed / pitch / timing settings changed since the voices were made: every line is stale
        same = timing.get("_settings", self._voice_settings()) == self._voice_settings()
        for s in segs:
            info = timing.get(str(s.id))
            if not s.km.strip() or not info:
                st = "none"
            elif not same or info.get("key") != line_key(s):
                st = "changed"
            else:
                st = info.get("status", "ok")
            counts[st] += 1
            factor = round((1 + (info or {}).get("rate", base) / 100) / (1 + base / 100), 2)
            lines[s.id] = {**(info or {}), "status": st, "factor": factor}
        return {"made": any(k != "_settings" for k in timing), "lines": lines, "counts": counts}

    def _voice_settings(self) -> dict:
        return {"speed": int(self.s.voice_speed), "pitch": int(self.s.voice_pitch), "mode": self.s.fit_mode,
                "max_speedup": float(self.s.max_speedup)}

    def line_preview(self, idx: int, seconds_before: float = 1.0, seconds_after: float = 1.5) -> Path:
        """A short clip of one line in context: picture, music, the Khmer voices and the subtitle."""
        import numpy as np

        from .media import save_wav
        from .render import FONTS_DIR
        from .subtitles import write_ass
        from .tts import TTS_SR, plan

        self.refine_bounds()
        segs = sorted((s for s in self.p.load_segments() if s.km.strip()), key=lambda s: s.start + s.offset)
        all_segs = self.p.load_segments()
        target = all_segs[idx]
        if not target.km.strip():
            raise RuntimeError("This line has no Khmer text yet.")
        info = video_info(self.p.video)
        k = next(i for i, s in enumerate(segs) if s.id == target.id)
        near = segs[max(0, k - 4): k + 4]  # neighbours decide pushes and room
        clips, placed = plan(near, self.p.path("tts"), info.duration, int(self.s.voice_speed),
                             int(self.s.voice_pitch), self.s.max_speedup, self.s.fit_mode)
        pl = placed[target.id]
        a = max(0.0, min(target.start + target.offset, pl.start) - seconds_before)
        b = min(info.duration, max(target.end + target.offset, pl.end) + seconds_after)
        self.extract_audio()
        bed_path = self.music_wav if (self.s.remove_voice and self.music_wav.exists()) else self.original_wav
        import soundfile as sf

        sr = sf.info(str(bed_path)).samplerate  # read only the seconds we need
        bed, _ = sf.read(str(bed_path), start=int(a * sr), stop=int(b * sr), dtype="float32", always_2d=True)
        bed = bed.mean(axis=1)
        if bed_path == self.original_wav:
            bed = bed * 0.25
        mix = bed * float(self.s.background_volume)
        for s in near:
            c, p = clips[s.id], placed[s.id]
            c = np.interp(np.arange(0, c.size, TTS_SR / sr), np.arange(c.size), c).astype("float32")  # 24 kHz -> sr
            i0 = int((p.start - a) * sr)
            if i0 >= mix.size or i0 + c.size <= 0:
                continue
            c0 = max(0, -i0)
            i0 = max(0, i0)
            part = c[c0: c0 + mix.size - i0] * float(self.s.dub_volume)
            mix[i0: i0 + part.size] += part
        peak = float(np.abs(mix).max()) if mix.size else 0
        if peak > 0.98:
            mix *= 0.98 / peak
        clips_dir = self.p.path("clips")
        clips_dir.mkdir(exist_ok=True)
        wav = clips_dir / "line_preview.wav"
        save_wav(wav, mix.astype("float32"), sr)
        # subtitle for the lines in view
        lines = [(placed[s.id].start, max(placed[s.id].end, s.end + s.offset), s.km) for s in near]
        fonts = self.p.path("fonts")
        fonts.mkdir(exist_ok=True)
        for f in FONTS_DIR.glob("*.ttf"):
            if not (fonts / f.name).exists():
                shutil.copy(f, fonts / f.name)
        write_ass(lines, self.p.path("line_preview.ass"), info.width, info.height, self.s.subtitle_size,
                  offset=a, **self.sub_style())
        out = clips_dir / f"line_{idx}_{int(time.time())}.mp4"
        for old in clips_dir.glob("line_*.mp4"):
            old.unlink(missing_ok=True)
        vf = "ass=line_preview.ass:fontsdir=fonts,scale=-2:'min(480,ih)',format=yuv420p"
        run_ffmpeg(["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(self.p.video), "-i", str(wav),
                    "-map", "0:v:0", "-map", "1:a:0", "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast",
                    "-crf", "26", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(out)],
                   cwd=self.p.dir)
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
               self.s.blur_style, "fast", self.s.resolution, None, self.sub_style(),
               start, seconds, self.stage(0.5, 1.0), self.log)
        return out


def _wav_seconds(path: Path) -> float:
    import soundfile as sf

    return sf.info(str(path)).duration


def estimate_minutes(duration_s: float, gpu: bool, remove_voice: bool = True, blur: bool = True,
                     scan_fps: float = 3.0) -> tuple[int, int]:
    """Rough processing time (min, max minutes).

    CPU numbers measured on a 12-core laptop (10-minute video, 2026-11): voice removal 0.82x the
    video length, transcript 0.35x, translation+voices+mix 0.15x, text scan 0.5x (at 3/s), render 0.23x.
    GPU numbers are estimates.
    """
    m = duration_s / 60
    if gpu:
        per_min = (0.08 if remove_voice else 0) + 0.06 + 0.15 + (0.35 * scan_fps / 3 if blur else 0) + 0.2
    else:
        per_min = (0.82 if remove_voice else 0) + 0.35 + 0.15 + (0.5 * scan_fps / 3 if blur else 0) + 0.23
    return max(1, round(m * per_min * 0.75)), max(2, round(m * per_min * 1.35))
