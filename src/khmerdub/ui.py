"""Web app (Gradio): upload a Chinese video, review the Khmer translation, get the Khmer video."""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
import traceback
from pathlib import Path

import gradio as gr

from .project import Project, Settings
from .translate import DEFAULT_MODELS, ENGINES

PROJECTS = Path("projects")
VOICE_ALIASES = {"sreymom": "sreymom", "s": "sreymom", "f": "sreymom", "female": "sreymom", "ស្រីមុំ": "sreymom",
                 "piseth": "piseth", "p": "piseth", "m": "piseth", "male": "piseth", "ពិសិដ្ឋ": "piseth"}
HEADERS = ["#", "Start (s)", "End (s)", "Chinese", "Khmer", "Voice"]

CSS = """
.khmer textarea, .khmer td { font-family: 'Noto Sans Khmer', 'Khmer OS', sans-serif; }
#title { margin-bottom: 0; }
"""


# ------------------------------------------------------------------ projects --
def list_projects() -> list[str]:
    if not PROJECTS.exists():
        return []
    items = [d for d in PROJECTS.iterdir() if d.is_dir() and (d / "settings.json").exists()]
    return [d.name for d in sorted(items, key=lambda d: d.stat().st_mtime, reverse=True)]


def _safe_name(stem: str) -> str:
    name = re.sub(r"[^\w\-]+", "_", stem, flags=re.UNICODE).strip("_") or "video"
    return name[:60]


def open_project(upload, existing: str | None) -> Project:
    if upload:
        src = Path(upload if isinstance(upload, str) else upload.name)
        d = PROJECTS / _safe_name(src.stem)
        d.mkdir(parents=True, exist_ok=True)
        dest = d / f"source{src.suffix.lower()}"
        if not dest.exists() or dest.stat().st_size != src.stat().st_size:
            shutil.copy(src, dest)
        return Project(dest, d)
    if existing:
        d = PROJECTS / existing
        vids = [p for p in d.glob("source.*")]
        if not vids:
            raise gr.Error(f"Project {existing} has no source video")
        return Project(vids[0], d)
    raise gr.Error("Upload a video first (or pick a project to continue).")


# ------------------------------------------------------------------ table -----
def segments_to_rows(proj: Project) -> list[list]:
    if not proj.has_segments():
        return []
    return [[s.id, round(s.start, 2), round(s.end, 2), s.zh, s.km, s.voice] for s in proj.load_segments()]


def rows_to_segments(proj: Project, rows) -> int:
    """Write table edits back to segments.json. Returns number of changed lines."""
    if not proj.has_segments() or rows is None:
        return 0
    if hasattr(rows, "values"):  # pandas DataFrame
        rows = rows.values.tolist()
    segs = {s.id: s for s in proj.load_segments()}
    changed = 0
    for r in rows:
        if not r or r[0] in ("", None):
            continue
        try:
            sid = int(float(r[0]))
        except (TypeError, ValueError):
            continue
        s = segs.get(sid)
        if s is None:
            continue
        km = str(r[4] or "").strip()
        voice = VOICE_ALIASES.get(str(r[5] or "").strip().lower(), s.voice)
        try:
            start, end = float(r[1]), float(r[2])
        except (TypeError, ValueError):
            start, end = s.start, s.end
        if (km, voice, round(start, 2), round(end, 2)) != (s.km, s.voice, round(s.start, 2), round(s.end, 2)):
            s.km, s.voice, s.start, s.end = km, voice, start, max(end, start + 0.2)
            changed += 1
    proj.save_segments(list(segs.values()))
    return changed


# ------------------------------------------------------------------ settings --
def build_settings(proj: Project, translator, model, whisper, voice, remove_voice, subtitles, sub_size,
                   blur_mode, blur_style, scan_fps, regions_json, max_speedup, bg_vol, dub_vol, quality) -> Settings:
    s = proj.load_settings()
    s.translator, s.translator_model, s.whisper_model = translator, (model or "").strip(), whisper
    s.voice_mode, s.remove_voice = voice, bool(remove_voice)
    s.subtitles, s.subtitle_size = subtitles, float(sub_size)
    s.blur, s.blur_style, s.blur_sample_fps = blur_mode, blur_style, float(scan_fps)
    s.max_speedup, s.background_volume, s.dub_volume, s.video_quality = float(max_speedup), float(bg_vol), float(dub_vol), quality
    try:
        regions = json.loads(regions_json or "[]")
        s.blur_regions = [r for r in regions if all(k in r for k in "xywh")]
    except json.JSONDecodeError as e:
        raise gr.Error(f"Manual blur boxes are not valid JSON: {e}") from e
    return s


# ------------------------------------------------------------------ runner ----
def run_in_background(work, progress: gr.Progress):
    """Run `work(log, prog)` in a thread; yield (log_text, done, result, error) about every second."""
    lines: list[str] = []
    state = {"f": 0.0, "m": "Starting…"}
    out: dict = {}

    def log(msg: str) -> None:
        lines.append(msg)

    def prog(f: float, m: str) -> None:
        state["f"], state["m"] = f, m

    def target():
        try:
            out["result"] = work(log, prog)
        except Exception as e:  # report to the UI
            out["error"] = e
            lines.append("ERROR: " + str(e))
            lines.append(traceback.format_exc(limit=3))

    th = threading.Thread(target=target, daemon=True)
    th.start()
    while th.is_alive():
        progress(state["f"], desc=state["m"])
        yield "\n".join(lines[-200:]), False, None, None
        time.sleep(1.0)
    yield "\n".join(lines[-200:]), True, out.get("result"), out.get("error")


# ------------------------------------------------------------------ app -------
def build_app() -> gr.Blocks:
    from .pipeline import Pipeline

    with gr.Blocks(title="Khmer Dub") as app:
        proj_dir = gr.State(None)
        gr.Markdown("# Khmer Dub\nChinese video → Khmer voice (Sreymom / Piseth) + Khmer subtitles + Chinese text blur",
                    elem_id="title")

        with gr.Row():
            # ---------------- left: input + settings
            with gr.Column(scale=1, min_width=320):
                gr.Markdown("### 1 · Video")
                upload = gr.File(label="Chinese video", file_types=["video"], type="filepath")
                with gr.Row():
                    existing = gr.Dropdown(label="…or continue a project", choices=list_projects(), value=None,
                                           scale=4)
                    refresh = gr.Button("↻", scale=1, min_width=40)

                with gr.Accordion("Translation & voice", open=True):
                    translator = gr.Dropdown(label="Translator", choices=[(v, k) for k, v in ENGINES.items()],
                                             value="google")
                    api_key = gr.Textbox(label="API key (Claude / ChatGPT / Gemini only)", type="password",
                                         placeholder="Leave empty to use the environment variable")
                    model = gr.Textbox(label="Model (optional)", placeholder="default")
                    voice = gr.Radio(label="Khmer voice",
                                     choices=[("Automatic: female → Sreymom, male → Piseth", "auto"),
                                              ("All Sreymom (female)", "sreymom"), ("All Piseth (male)", "piseth")],
                                     value="auto")
                    remove_voice = gr.Checkbox(label="Remove the Chinese voice (keep music & sound effects)", value=True)
                    whisper = gr.Dropdown(label="Speech recognition model",
                                          choices=[("Auto (best for this computer)", "auto"), ("small (fastest)", "small"),
                                                   ("medium", "medium"), ("large-v3-turbo (GPU)", "large-v3-turbo"),
                                                   ("large-v3 (slowest, best)", "large-v3")], value="auto")

                with gr.Accordion("Subtitles", open=False):
                    subtitles = gr.Radio(label="Khmer subtitles",
                                         choices=[("Burn into the video", "burn"), ("Separate track (can turn off)", "soft"),
                                                  ("None", "none")], value="burn")
                    sub_size = gr.Slider(label="Subtitle size", minimum=0.6, maximum=1.8, step=0.05, value=1.0)

                with gr.Accordion("Blur Chinese text", open=False):
                    blur_mode = gr.Radio(label="Automatic blur",
                                         choices=[("Chinese text only", "chinese"), ("All text", "all"), ("Off", "off")],
                                         value="chinese")
                    blur_style = gr.Radio(label="Style", choices=[("Blur", "blur"), ("Pixelate", "pixelate"),
                                                                 ("Dark box", "box")], value="blur")
                    scan_fps = gr.Radio(label="Scan", choices=[("Fast (2/s)", 2.0), ("Normal (3/s)", 3.0),
                                                              ("Careful (5/s)", 5.0)], value=3.0)
                    gr.Markdown("**Manual boxes** – for anything the automatic blur misses. "
                                "Position in % of the frame; leave times empty for the whole video.")
                    frame_t = gr.Number(label="Show frame at (seconds)", value=10)
                    frame_img = gr.Image(label="Frame", interactive=False, height=220)
                    with gr.Row():
                        bx = gr.Slider(0, 100, value=0, step=0.5, label="x %")
                        by = gr.Slider(0, 100, value=80, step=0.5, label="y %")
                    with gr.Row():
                        bw = gr.Slider(1, 100, value=100, step=0.5, label="width %")
                        bh = gr.Slider(1, 100, value=14, step=0.5, label="height %")
                    with gr.Row():
                        b_start = gr.Number(label="from (s)", value=None)
                        b_end = gr.Number(label="to (s)", value=None)
                    with gr.Row():
                        show_frame = gr.Button("Show frame")
                        add_box = gr.Button("Add box")
                        clear_boxes = gr.Button("Clear")
                    regions = gr.Code(label="Boxes (JSON)", language="json", value="[]", lines=3)

                with gr.Accordion("Advanced", open=False):
                    max_speedup = gr.Slider(label="Max voice speed-up to fit timing", minimum=1.0, maximum=2.0,
                                            step=0.05, value=1.5)
                    bg_vol = gr.Slider(label="Background (music) volume", minimum=0, maximum=2, step=0.05, value=1.0)
                    dub_vol = gr.Slider(label="Khmer voice volume", minimum=0.2, maximum=2, step=0.05, value=1.0)
                    quality = gr.Radio(label="Video quality", choices=[("Fast", "fast"), ("Balanced", "balanced"),
                                                                      ("High", "high")], value="balanced")
                    zh_srt = gr.File(label="Optional: Chinese .srt (skip speech recognition)", file_types=[".srt"],
                                     type="filepath")
                    km_srt = gr.File(label="Optional: Khmer .srt (skip transcript + translation)", file_types=[".srt"],
                                     type="filepath")

            # ---------------- right: review + output
            with gr.Column(scale=2):
                gr.Markdown("### 2 · Transcript & Khmer translation")
                btn_prepare = gr.Button("Step 1 · Transcribe & translate", variant="primary")
                table = gr.Dataframe(headers=HEADERS, datatype=["number", "number", "number", "str", "str", "str"],
                                     type="array", interactive=True, wrap=True, max_height=520,
                                     column_widths=["5%", "8%", "8%", "30%", "39%", "10%"], elem_classes="khmer",
                                     label="Edit the Khmer text or the voice (sreymom / piseth), then make the video")
                with gr.Row():
                    btn_save = gr.Button("Save edits")
                    btn_retranslate = gr.Button("Translate all again (with the selected translator)")

                gr.Markdown("### 3 · Khmer video")
                with gr.Row():
                    preview_at = gr.Number(label="Preview 20 s starting at (seconds)", value=0, scale=2)
                    btn_preview = gr.Button("Make preview", scale=1)
                btn_produce = gr.Button("Step 2 · Make the Khmer video", variant="primary")
                out_video = gr.Video(label="Result", interactive=False)
                out_files = gr.File(label="Downloads", file_count="multiple", interactive=False)
                log_box = gr.Textbox(label="Log", lines=8, max_lines=20, autoscroll=True)

        settings_inputs = [translator, model, whisper, voice, remove_voice, subtitles, sub_size, blur_mode, blur_style,
                           scan_fps, regions, max_speedup, bg_vol, dub_vol, quality]

        # ---------------- handlers (inputs given as a set -> handler gets {component: value})
        def _project(d):
            if d.get(upload) or d.get(existing):
                return open_project(d.get(upload), d.get(existing))
            if d.get(proj_dir):
                pdir = Path(d[proj_dir])
                return Project(next(pdir.glob("source.*")), pdir)
            return open_project(None, None)

        def _settings(proj, d):
            return build_settings(proj, *[d[c] for c in settings_inputs])

        def _prepare(d, retranslate, progress):
            proj = _project(d)
            s = _settings(proj, d)
            zh, km = d.get(zh_srt), d.get(km_srt)

            def work(log, prog):
                return Pipeline(proj, s, d.get(api_key) or None, log, prog).prepare(
                    Path(zh) if zh else None, Path(km) if km else None, retranslate)

            text = ""
            for text, done, _res, err in run_in_background(work, progress):
                yield {log_box: text, proj_dir: str(proj.dir)}
            if err:
                raise gr.Error(str(err)[:500])
            yield {table: segments_to_rows(proj), log_box: text, proj_dir: str(proj.dir),
                   existing: gr.update(choices=list_projects(), value=proj.dir.name)}

        def do_prepare(d, progress=gr.Progress()):
            yield from _prepare(d, False, progress)

        def do_retranslate(d, progress=gr.Progress()):
            yield from _prepare(d, True, progress)

        def do_save(d):
            if not d.get(proj_dir):
                raise gr.Error("Nothing to save yet – run Step 1 first.")
            proj = _project(d)
            n = rows_to_segments(proj, d.get(table))
            gr.Info(f"Saved ({n} lines changed)")
            return segments_to_rows(proj)

        def do_produce(d, progress=gr.Progress()):
            proj = _project(d)
            if not proj.has_segments():
                raise gr.Error("Run Step 1 first.")
            rows_to_segments(proj, d.get(table))
            s = _settings(proj, d)

            def work(log, prog):
                return Pipeline(proj, s, None, log, prog).produce()

            text, res = "", None
            for text, done, res, err in run_in_background(work, progress):
                yield {log_box: text}
            if err:
                raise gr.Error(str(err)[:500])
            files = [str(res), *[str(p) for p in proj.dir.glob("*_khmer.srt")], str(proj.path("chinese.srt"))]
            yield {out_video: str(res), out_files: [f for f in files if Path(f).exists()], log_box: text}

        def do_preview(d, progress=gr.Progress()):
            proj = _project(d)
            if proj.has_segments():
                rows_to_segments(proj, d.get(table))
            s = _settings(proj, d)

            def work(log, prog):
                return Pipeline(proj, s, None, log, prog).preview(float(d.get(preview_at) or 0))

            text, res = "", None
            for text, done, res, err in run_in_background(work, progress):
                yield {log_box: text, proj_dir: str(proj.dir)}
            if err:
                raise gr.Error(str(err)[:500])
            yield {out_video: str(res), log_box: text, proj_dir: str(proj.dir)}

        def do_show_frame(d):
            import cv2

            proj = _project(d)
            cap = cv2.VideoCapture(str(proj.video))
            cap.set(cv2.CAP_PROP_POS_MSEC, float(d.get(frame_t) or 0) * 1000)
            ok, frame = cap.read()
            cap.release()
            if not ok:
                raise gr.Error("Could not read that frame")
            H, W = frame.shape[:2]
            try:
                boxes = json.loads(d.get(regions) or "[]")
            except json.JSONDecodeError:
                boxes = []
            for r in boxes:
                cv2.rectangle(frame, (int(r["x"] * W), int(r["y"] * H)),
                              (int((r["x"] + r["w"]) * W), int((r["y"] + r["h"]) * H)), (0, 200, 255), 3)
            x, y, w, h = d[bx], d[by], d[bw], d[bh]
            cv2.rectangle(frame, (int(x / 100 * W), int(y / 100 * H)),
                          (int((x + w) / 100 * W), int((y + h) / 100 * H)), (0, 0, 255), 3)
            return {frame_img: cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), proj_dir: str(proj.dir)}

        def do_add_box(regions_v, x, y, w, h, a, b):
            try:
                boxes = json.loads(regions_v or "[]")
            except json.JSONDecodeError:
                boxes = []
            box = {"x": round(x / 100, 4), "y": round(y / 100, 4), "w": round(min(w, 100 - x) / 100, 4),
                   "h": round(min(h, 100 - y) / 100, 4)}
            if a not in (None, "") and b not in (None, "") and float(b) > float(a):
                box["start"], box["end"] = float(a), float(b)
            boxes.append(box)
            return json.dumps(boxes, indent=1)

        def do_load_existing(name):
            if not name:
                return gr.update(), gr.update(), gr.update()
            proj = open_project(None, name)
            return segments_to_rows(proj), str(proj.dir), json.dumps(proj.load_settings().blur_regions, indent=1)

        common = {upload, existing, proj_dir, table, *settings_inputs}
        btn_prepare.click(do_prepare, {*common, api_key, zh_srt, km_srt}, [table, log_box, proj_dir, existing])
        btn_retranslate.click(do_retranslate, {*common, api_key, zh_srt, km_srt}, [table, log_box, proj_dir, existing])
        btn_save.click(do_save, common, [table])
        btn_produce.click(do_produce, common, [out_video, out_files, log_box])
        btn_preview.click(do_preview, {*common, preview_at}, [out_video, log_box, proj_dir])
        frame_in = {upload, existing, proj_dir, frame_t, regions, bx, by, bw, bh}
        show_frame.click(do_show_frame, frame_in, [frame_img, proj_dir])
        for sl in (bx, by, bw, bh):
            sl.release(do_show_frame, frame_in, [frame_img, proj_dir])
        add_box.click(do_add_box, [regions, bx, by, bw, bh, b_start, b_end], [regions]).then(
            do_show_frame, frame_in, [frame_img, proj_dir])
        clear_boxes.click(lambda: "[]", None, [regions])
        refresh.click(lambda: gr.update(choices=list_projects()), None, [existing])
        existing.change(do_load_existing, [existing], [table, proj_dir, regions])

        translator.change(lambda t: gr.update(placeholder=DEFAULT_MODELS.get(t, "default")), [translator], [model])

    return app


def launch(port: int = 7860, share: bool = False, projects_dir: str | None = None,
           inbrowser: bool = True) -> None:
    global PROJECTS
    if projects_dir:
        PROJECTS = Path(projects_dir)
    PROJECTS.mkdir(parents=True, exist_ok=True)
    PROJECTS = PROJECTS.resolve()
    app = build_app()
    app.queue(default_concurrency_limit=1).launch(
        server_port=port, share=share, inbrowser=inbrowser, allowed_paths=[str(PROJECTS)],
        theme=gr.themes.Soft(), css=CSS, max_file_size="20gb",
    )
