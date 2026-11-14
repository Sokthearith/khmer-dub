"""A project = one input video + a work folder holding every intermediate result.

Every pipeline step writes its output into the work folder, so a crash, or a
re-run after fixing a translation, only redoes what is missing or changed.

`segments.json` is the human-editable heart of a project: one entry per spoken
line with the Chinese text, the Khmer text and the voice to use.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

VOICES = {
    "sreymom": "km-KH-SreymomNeural",  # female
    "piseth": "km-KH-PisethNeural",  # male
}


@dataclass
class Segment:
    id: int
    start: float
    end: float
    zh: str
    km: str = ""
    voice: str = "sreymom"  # key of VOICES
    pitch: float = 0.0  # median pitch of the original speaker (Hz), 0 = unknown
    checked: bool = False  # the creator reviewed this line in the app
    offset: float = 0.0  # seconds to move the Khmer voice later (+) or earlier (-)
    rate: int | None = None  # fixed speaking speed in % for this line (None = automatic)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class Settings:
    # speech recognition
    whisper_model: str = "auto"
    # translation
    translator: str = "google"
    translator_model: str = ""  # optional model override for AI translators
    translator_provider: str = "openrouter"  # for translator == "custom"
    translator_base_url: str = ""  # for translator == "custom" / provider "other"
    # voice
    voice_mode: str = "auto"  # auto | sreymom | piseth
    voice_speed: int = 0  # % faster (+) or slower (-), applied to every line
    voice_pitch: int = 0  # Hz higher (+) or lower (-)
    remove_voice: bool = True
    background_volume: float = 1.0
    dub_volume: float = 1.0
    max_speedup: float = 1.5
    fit_mode: str = "match"  # match = start and end with the character | natural = only speed up when needed
    # subtitles
    subtitles: str = "burn"  # burn | soft | none
    subtitle_size: float = 1.0
    subtitle_position: str = "bottom"  # bottom | top
    subtitle_color: str = "white"  # white | yellow
    subtitle_box: bool = False  # dark box behind the text
    # blur
    blur: str = "off"  # off | chinese | all  (automatic text finding; your own boxes are always used)
    blur_targets: list[str] = field(default_factory=lambda: ["subtitles", "logos"])  # + "other" (see blur.py)
    blur_regions: list[dict] = field(default_factory=list)  # manual boxes, see blur.py
    blur_style: str = "blur"  # blur | pixelate | box
    blur_sample_fps: float = 3.0
    # output
    video_quality: str = "balanced"  # fast | balanced | high
    resolution: str = "original"  # original | 1080 | 720 | 480
    keep_original_audio: bool = False  # add the Chinese soundtrack as a 2nd audio track


class Project:
    def __init__(self, video: str | Path, workdir: str | Path | None = None):
        self.video = Path(video).resolve()
        if not self.video.exists():
            raise FileNotFoundError(self.video)
        self.dir = Path(workdir) if workdir else self.video.parent / f"{self.video.stem}_khmerdub"
        self.dir = self.dir.resolve()
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "tts").mkdir(exist_ok=True)

    # ---- paths -----------------------------------------------------------
    def path(self, name: str) -> Path:
        return self.dir / name

    @property
    def segments_file(self) -> Path:
        return self.dir / "segments.json"

    @property
    def settings_file(self) -> Path:
        return self.dir / "settings.json"

    @property
    def output_video(self) -> Path:
        return self.dir / f"{self.video.stem}_khmer.mp4"

    # ---- settings ----------------------------------------------------------
    def load_settings(self) -> Settings:
        if self.settings_file.exists():
            data = json.loads(self.settings_file.read_text(encoding="utf-8"))
            known = Settings.__dataclass_fields__.keys()
            return Settings(**{k: v for k, v in data.items() if k in known})
        return Settings()

    def save_settings(self, s: Settings) -> None:
        self.settings_file.write_text(
            json.dumps(asdict(s), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ---- segments ----------------------------------------------------------
    def has_segments(self) -> bool:
        return self.segments_file.exists()

    def load_segments(self) -> list[Segment]:
        data = json.loads(self.segments_file.read_text(encoding="utf-8"))
        known = Segment.__dataclass_fields__.keys()
        segs = [Segment(**{k: v for k, v in d.items() if k in known}) for d in data]
        segs.sort(key=lambda s: s.start)
        return segs

    def save_segments(self, segs: list[Segment]) -> None:
        self.segments_file.write_text(
            json.dumps([asdict(s) for s in segs], ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
