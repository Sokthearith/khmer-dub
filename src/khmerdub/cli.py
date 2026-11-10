"""Command line:  khmerdub ui   |   khmerdub run VIDEO [options]"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# only real problems from the model libraries in the black window (not "set a HF_TOKEN" and similar notices)
os.environ.setdefault("HF_HUB_VERBOSITY", "error")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

from .project import Project  # noqa: E402
from .translate import ENGINES  # noqa: E402


def _targets(value: str) -> list[str]:
    from .blur import TARGETS

    names = [x.strip() for x in value.split(",") if x.strip()]
    bad = [x for x in names if x not in TARGETS.values()]
    if bad:
        raise SystemExit(f"--blur-targets: unknown {', '.join(bad)}. Use any of: {', '.join(TARGETS.values())}.")
    return names


def _region(s: str) -> dict:
    """x,y,w,h[,start,end] as fractions of the frame (0-1), times in seconds."""
    parts = [float(p) for p in s.split(",")]
    if len(parts) not in (4, 6):
        raise argparse.ArgumentTypeError("use x,y,w,h or x,y,w,h,start,end (fractions 0-1, seconds)")
    r = dict(zip("xywh", parts[:4]))
    if len(parts) == 6:
        r["start"], r["end"] = parts[4], parts[5]
    return r


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="khmerdub", description="Chinese video -> Khmer dub + subtitles + text blur")
    sub = ap.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("app", help="open Khmer Dub in its own window (what the start scripts use)")
    w.add_argument("--projects", default=None, help="folder for projects (default: ./projects)")
    w.add_argument("--port", type=int, default=None, help="local port (default: first free from 7860)")
    w.add_argument("--no-shortcuts", action="store_true", help="don't create desktop / menu shortcuts")

    sub.add_parser("shortcut", help="(re)create the Khmer Dub shortcuts on the desktop / Start menu / Applications")

    up = sub.add_parser("update", help="check for a new version and download it (installed at the next start)")
    up.add_argument("--apply", action="store_true", help="install a downloaded update now (the start scripts do this)")

    ui = sub.add_parser("ui", help="open the web app in your browser")
    ui.add_argument("--port", type=int, default=7860)
    ui.add_argument("--share", action="store_true", help="also create a temporary public link")
    ui.add_argument("--projects", default=None, help="folder for projects (default: ./projects)")
    ui.add_argument("--no-browser", action="store_true", help="don't open the browser automatically")

    c = sub.add_parser("cut", help="keep a time range and/or split a video into parts")
    c.add_argument("video")
    c.add_argument("--every", type=float, help="split into parts of this many minutes (e.g. 10 or 15)")
    c.add_argument("--from", dest="start", help="start time, e.g. 1:30 (default: beginning)")
    c.add_argument("--to", dest="end", help="end time, e.g. 45:00 (default: end)")
    c.add_argument("--out", help="output folder (default: <video>_parts next to the video)")

    r = sub.add_parser("run", help="process a video from the command line")
    r.add_argument("video")
    r.add_argument("--workdir", help="project folder (default: <video>_khmerdub next to the video)")
    r.add_argument("--stage", choices=["prepare", "produce", "all"], default="all",
                   help="prepare = transcript+translation only (then edit segments.json); produce = voice+video")
    r.add_argument("--translator", choices=list(ENGINES), help="translation engine")
    r.add_argument("--translator-model", help="model name for AI translators")
    r.add_argument("--provider", choices=["openrouter", "groq", "deepseek", "ollama", "other"],
                   help="AI service for --translator custom")
    r.add_argument("--base-url", help="API address for --translator custom --provider other")
    r.add_argument("--api-key", help="API key for the translator (or set the env var)")
    r.add_argument("--retranslate", action="store_true", help="translate all lines again")
    r.add_argument("--whisper-model", help="auto | small | medium | large-v3 | large-v3-turbo")
    r.add_argument("--voice", choices=["auto", "sreymom", "piseth"], help="auto = by speaker pitch")
    r.add_argument("--voice-speed", type=int, help="speaking speed in %% (e.g. 10 or -10)")
    r.add_argument("--voice-pitch", type=int, help="voice pitch in Hz (e.g. 4 or -4)")
    r.add_argument("--keep-chinese-voice", action="store_true", help="don't remove the Chinese voice, just lower it")
    r.add_argument("--keep-chinese-audio", action="store_true",
                   help="also add the original Chinese sound as a 2nd audio track")
    r.add_argument("--zh-srt", help="use this Chinese .srt instead of speech recognition")
    r.add_argument("--km-srt", help="use this Khmer .srt (skip transcript and translation)")
    r.add_argument("--subtitles", choices=["burn", "soft", "none"])
    r.add_argument("--subtitle-size", type=float)
    r.add_argument("--subtitle-position", choices=["bottom", "top"])
    r.add_argument("--subtitle-color", choices=["white", "yellow"])
    r.add_argument("--subtitle-box", action="store_true", help="dark box behind the subtitles")
    r.add_argument("--resolution", choices=["original", "1080", "720", "480"])
    r.add_argument("--blur", choices=["chinese", "all", "off"], help="automatic text blur")
    r.add_argument("--blur-region", type=_region, action="append", default=None,
                   help="manual blur box x,y,w,h[,start,end] in fractions of the frame; repeatable")
    r.add_argument("--blur-style", choices=["blur", "pixelate", "box"])
    r.add_argument("--blur-targets", help="what to blur, comma separated: subtitles,logos,other "
                                          "(default subtitles,logos)")
    r.add_argument("--blur-fps", type=float, help="text scan samples per second (default 3)")
    r.add_argument("--max-speedup", type=float, help="max speed-up of Khmer voice to fit timing (default 1.5)")
    r.add_argument("--quality", choices=["fast", "balanced", "high"])
    r.add_argument("--preview", type=float, metavar="SECONDS",
                   help="only render a 20s preview starting at SECONDS")

    a = ap.parse_args(argv)
    if a.cmd == "app":
        from .desktop import ensure_shortcuts
        from .ui import launch

        if not a.no_shortcuts:
            ensure_shortcuts()
        launch(port=a.port, projects_dir=a.projects, window=True)
        return

    if a.cmd == "update":
        from . import updater

        if a.apply:
            updater.apply_pending()
            return
        print(f"This is Khmer Dub {updater.current_version()}.")
        rel = updater.check(use_cache=False)
        if not rel:
            print("You have the newest version.")
            return
        print(f"Khmer Dub {rel.version} is available: {rel.page_url}")
        if updater.is_git_checkout():
            print("This copy is a git folder: update it with `git pull`.")
            return
        updater.stage(rel)
        print("Downloaded. Close Khmer Dub and start it again to finish the update.")
        return

    if a.cmd == "shortcut":
        from .desktop import make_shortcuts

        make_shortcuts()
        return

    if a.cmd == "ui":
        from .ui import launch

        launch(port=a.port, share=a.share, projects_dir=a.projects, inbrowser=not a.no_browser)
        return

    if a.cmd == "cut":
        from .cut import cut

        v = Path(a.video)
        parts = cut(v, Path(a.out) if a.out else v.parent / f"{v.stem}_parts", a.every, a.start, a.end)
        for part in parts:
            print(part)
        return

    proj = Project(a.video, a.workdir)
    s = proj.load_settings()
    for attr, val in [("translator", a.translator), ("translator_model", a.translator_model),
                      ("whisper_model", a.whisper_model), ("voice_mode", a.voice), ("subtitles", a.subtitles),
                      ("subtitle_size", a.subtitle_size), ("blur", a.blur), ("blur_style", a.blur_style),
                      ("blur_sample_fps", a.blur_fps), ("max_speedup", a.max_speedup), ("video_quality", a.quality),
                      ("blur_regions", a.blur_region), ("translator_provider", a.provider),
                      ("blur_targets", _targets(a.blur_targets) if a.blur_targets else None),
                      ("translator_base_url", a.base_url), ("voice_speed", a.voice_speed),
                      ("voice_pitch", a.voice_pitch), ("subtitle_position", a.subtitle_position),
                      ("subtitle_color", a.subtitle_color), ("resolution", a.resolution)]:
        if val is not None:
            setattr(s, attr, val)
    if a.keep_chinese_voice:
        s.remove_voice = False
    if a.keep_chinese_audio:
        s.keep_original_audio = True
    if a.subtitle_box:
        s.subtitle_box = True

    def progress(f: float, msg: str) -> None:
        sys.stderr.write(f"\r{f * 100:5.1f}%  {msg[:90]:<90}")
        sys.stderr.flush()

    def log(msg: str) -> None:
        sys.stderr.write("\r" + " " * 100 + "\r")
        print(msg, flush=True)

    from .pipeline import Pipeline

    pipe = Pipeline(proj, s, a.api_key, log, progress)
    if a.preview is not None:
        out = pipe.preview(a.preview)
        log(f"Preview: {out}")
        return
    if a.stage in ("prepare", "all"):
        pipe.prepare(Path(a.zh_srt) if a.zh_srt else None, Path(a.km_srt) if a.km_srt else None, a.retranslate)
        if a.stage == "prepare":
            log(f"Review/edit the Khmer lines in {proj.segments_file}, then run with --stage produce")
            return
    pipe.produce()
    print(json.dumps({"video": str(proj.output_video),
                      "srt": str(proj.path(f'{proj.video.stem}_khmer.srt'))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
