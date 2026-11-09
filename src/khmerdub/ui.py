"""Web app: a guided, step-by-step Chinese → Khmer dubbing studio (Gradio).

Tabs:  1 Upload · 2 Settings · 3 Review · 4 Blur · 5 Export · Batch · Help
"""

from __future__ import annotations

import re
import shutil
import threading
import time
import traceback
from pathlib import Path

import gradio as gr

from .project import Project, Settings
from .translate import DEFAULT_MODELS, ENGINES, PROVIDERS

PROJECTS = Path("projects")
TABLE_HEADERS = ["#", "Time", "Chinese", "Khmer", "Voice"]

# Settings field names, in the same order as the components passed to `comp` in build_app().
SETTING_FIELDS = [
    "translator", "translator_provider", "translator_base_url", "translator_model", "whisper_model",
    "voice_mode", "voice_speed", "voice_pitch", "remove_voice", "max_speedup", "background_volume", "dub_volume",
    "subtitles", "subtitle_size", "subtitle_position", "subtitle_color", "subtitle_box",
    "blur", "blur_style", "blur_sample_fps", "video_quality", "resolution", "keep_original_audio",
]

PRESETS = {
    "free": {"translator": "google", "whisper_model": "auto", "blur_sample_fps": 3.0, "video_quality": "balanced"},
    "gemini": {"translator": "gemini", "whisper_model": "auto", "blur_sample_fps": 3.0, "video_quality": "balanced"},
    "best": {"translator": "claude", "whisper_model": "auto", "blur_sample_fps": 5.0, "video_quality": "high"},
    "fastest": {"translator": "google", "whisper_model": "small", "blur_sample_fps": 2.0, "video_quality": "fast"},
}
PRESET_CHOICES = [
    ("⚡ Free & easy: Google Translate, no key needed", "free"),
    ("🆓 Free AI: Gemini, better Khmer (free key)", "gemini"),
    ("⭐ Best quality: Claude, most natural Khmer (paid key)", "best"),
    ("🚀 Fastest: for long series on slow laptops", "fastest"),
    ("🛠 Custom: I choose everything myself", "custom"),
]

TRANSLATOR_HELP = {
    "google": "Free, no account needed. Translates line by line, so it can sound stiff. Good for a first try.",
    "gemini": "Get a **free** key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). "
              "Understands the story, keeps names consistent.",
    "claude": "Best, most natural spoken Khmer. Key at [console.anthropic.com](https://console.anthropic.com) "
              "(paid, usually a few cents per episode).",
    "openai": "Key at [platform.openai.com](https://platform.openai.com) (paid).",
    "custom": "Use another AI service. Pick it below: **OpenRouter** and **Groq** have free keys, "
              "**DeepSeek** is very cheap, **Ollama** runs free on your own computer.",
    "nllb": "Runs on this computer, no internet or key. Downloads a 2.5 GB model the first time "
            "(needs `uv sync --extra cpu --extra offline` once). Basic quality.",
}

CSS = """
.gradio-container { max-width: 1280px !important; margin: auto; }
#hero { padding: 22px 26px; border-radius: 16px; color: #fff;
        background: linear-gradient(120deg, #312e81 0%, #4f46e5 55%, #d97706 120%); }
#hero h1 { margin: 0 0 4px 0; font-size: 1.9rem; color: #fff; }
#hero p { margin: 0; opacity: .92; font-size: 1.02rem; color: #fff; }
#hero .km { font-family: 'Kantumruy Pro', 'Noto Sans Khmer', sans-serif; opacity: .85; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 2px; }
.chip { padding: 5px 12px; border-radius: 999px; font-size: .88rem; border: 1px solid var(--border-color-primary);
        background: var(--background-fill-secondary); color: var(--body-text-color-subdued); }
.chip.done { background: #dcfce7; border-color: #86efac; color: #166534; }
.chip.now { background: #e0e7ff; border-color: #a5b4fc; color: #3730a3; }
.dark .chip.done { background: #14532d; border-color: #166534; color: #dcfce7; }
.dark .chip.now { background: #312e81; border-color: #4338ca; color: #e0e7ff; }
.card { border: 1px solid var(--border-color-primary); border-radius: 12px; padding: 14px 16px;
        background: var(--background-fill-secondary); }
.card h3 { margin-top: 0; }
.hint { font-size: .93rem; color: var(--body-text-color-subdued); }
.big-btn { font-size: 1.08rem !important; padding: 14px !important; }
.khmer, .khmer textarea, .khmer td, .khmer input { font-family: 'Kantumruy Pro', 'Noto Sans Khmer', sans-serif !important; }
.khmer textarea { font-size: 1.1rem !important; line-height: 1.7 !important; }
"""


# =========================================================== project helpers ==
def list_projects() -> list[str]:
    if not PROJECTS.exists():
        return []
    items = [d for d in PROJECTS.iterdir() if d.is_dir() and any(d.glob("source.*"))]
    return [d.name for d in sorted(items, key=lambda d: d.stat().st_mtime, reverse=True)]


def _safe_name(stem: str) -> str:
    return (re.sub(r"[^\w\-]+", "_", stem, flags=re.UNICODE).strip("_") or "video")[:60]


def project_from_upload(path: str) -> Project:
    """Same video again -> same project (continue). Different video with the same name -> new folder."""
    src = Path(path)
    base = _safe_name(src.stem)
    for n in range(1, 1000):
        d = PROJECTS / (base if n == 1 else f"{base}_{n}")
        old = list(d.glob("source.*")) if d.exists() else []
        if not old or (old[0].stat().st_size == src.stat().st_size and old[0].suffix == src.suffix.lower()):
            break
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"source{src.suffix.lower()}"
    if not dest.exists():
        shutil.copy(src, dest)
    proj = Project(dest, d)
    if not proj.settings_file.exists():
        proj.save_settings(Settings())
    return proj


def project_from_dir(d: str | Path | None) -> Project:
    if not d:
        raise gr.Error("First upload a video (tab 1) or pick a saved project.")
    d = Path(d)
    vids = list(d.glob("source.*"))
    if not vids:
        raise gr.Error(f"No video found in {d}")
    return Project(vids[0], d)


def fmt_t(t: float) -> str:
    m, s = divmod(max(0.0, t), 60)
    h, m = divmod(m, 60)
    return f"{int(h)}:{int(m):02d}:{s:04.1f}" if h else f"{int(m)}:{s:04.1f}"


def table_rows(proj: Project) -> list[list]:
    if not proj.has_segments():
        return []
    def short(t: float) -> str:
        m, sec = divmod(int(t), 60)
        return f"{m // 60}:{m % 60:02d}:{sec:02d}" if m >= 60 else f"{m}:{sec:02d}"

    return [[s.id, short(s.start), s.zh, s.km, "👩 Sreymom" if s.voice == "sreymom" else "👨 Piseth"]
            for s in proj.load_segments()]


def status_html(proj: Project | None, working: str = "") -> str:
    if proj is None:
        steps = [("Start by uploading a video", False)]
    else:
        p = proj.path
        segs = proj.load_segments() if proj.has_segments() else []
        n_km = sum(1 for s in segs if s.km.strip())
        steps = [
            (f"🎬 {proj.dir.name}", True),
            ("Chinese voice removed", p("music.wav").exists()),
            (f"Transcript ({len(segs)} lines)" if segs else "Transcript", bool(segs)),
            (f"Khmer {n_km}/{len(segs)}" if segs else "Khmer translation", bool(segs) and n_km == len(segs)),
            ("Text scan", any(proj.dir.glob("blur_*.json"))),
            ("Khmer voice", p("mix.m4a").exists()),
            ("Final video", proj.output_video.exists()),
        ]
    chips = "".join(f'<span class="chip {"done" if ok else ""}">{"✓ " if ok else ""}{label}</span>'
                    for label, ok in steps)
    if working:
        chips += f'<span class="chip now">⏳ {working}</span>'
    return f'<div class="chips">{chips}</div>'


def video_card(proj: Project) -> str:
    from .devices import torch_device
    from .media import video_info
    from .pipeline import estimate_minutes

    info = video_info(proj.video)
    s = proj.load_settings()
    gpu = torch_device() == "cuda"
    lo, hi = estimate_minutes(info.duration, gpu, s.remove_voice, s.blur != "off", s.blur_sample_fps)
    hw = "NVIDIA GPU found 🚀" if gpu else "no GPU (CPU only, slower)"
    size_mb = proj.video.stat().st_size / 1e6
    return (f'<div class="card"><h3>🎬 {proj.dir.name}</h3>'
            f"<b>Length:</b> {fmt_t(info.duration)} &nbsp;·&nbsp; <b>Picture:</b> {info.width}×{info.height}, "
            f"{size_mb:,.0f} MB<br><b>This computer:</b> {hw}<br>"
            f"<b>Estimated time for everything:</b> about {lo}–{hi} minutes"
            f'<p class="hint">Your progress is saved as it goes, so you can stop and continue later. '
            f"Keep the black window open while it works.</p></div>")


def frame_at(proj: Project, t: float, width: int = 960):
    import cv2

    cap = cv2.VideoCapture(str(proj.video))
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return None, 1.0
    scale = width / frame.shape[1]
    return cv2.resize(frame, (width, round(frame.shape[0] * scale))), scale


# =========================================================== background runs ==
def run_in_background(work, progress: gr.Progress):
    """Run `work(log, prog)` in a thread; yield (log_text, message, done, result, error) every second."""
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
        except Exception as e:  # shown in the app
            out["error"] = e
            lines.append("ERROR: " + str(e))
            lines.append(traceback.format_exc(limit=4))

    th = threading.Thread(target=target, daemon=True)
    th.start()
    while th.is_alive():
        progress(state["f"], desc=state["m"])
        yield "\n".join(lines[-300:]), state["m"], False, None, None
        time.sleep(1.0)
    yield "\n".join(lines[-300:]), state["m"], True, out.get("result"), out.get("error")


def _friendly(err: Exception) -> str:
    msg = str(err)
    if "Could not extract audio" in msg:
        return "This video has no sound track, or the file is damaged."
    if "edge" in msg.lower() or "WSServerHandshake" in msg or "ClientConnector" in msg:
        return ("Could not reach the Khmer voice service (it needs internet). Check the connection and press "
                "the button again; it continues where it stopped.")
    return msg[:600]


def _box_rows(box_list) -> list[list]:
    return [[round(b["x"] * 100, 1), round(b["y"] * 100, 1), round(b["w"] * 100, 1), round(b["h"] * 100, 1),
             b.get("start", "start"), b.get("end", "end")] for b in box_list or []]


def _save_boxes(proj: Project, box_list) -> None:
    s = proj.load_settings()
    s.blur_regions = list(box_list)
    proj.save_settings(s)


# =========================================================== the app ==========
def build_app() -> gr.Blocks:  # noqa: C901 - one layout function is the easiest way to read UI code
    from .pipeline import Pipeline

    with gr.Blocks(title="Khmer Dub") as app:
        proj_dir = gr.State(None)
        boxes = gr.State([])  # manual blur boxes (fractions of the frame)
        pending_pt = gr.State(None)  # first click of a new blur box
        line_idx = gr.State(0)  # position of the line shown in the editor

        gr.HTML('<div id="hero"><h1>Khmer Dub</h1>'
                '<p>Chinese video → Khmer voice (Sreymom &amp; Piseth) + Khmer subtitles + Chinese text blur</p>'
                '<p class="km">បម្លែងវីដេអូចិន ទៅជាវីដេអូនិយាយខ្មែរ</p></div>')
        status = gr.HTML(status_html(None))

        with gr.Tabs() as tabs:
            # ------------------------------------------------------- 1 upload
            with gr.Tab("1 · Upload", id="upload"):
                with gr.Row(equal_height=False):
                    with gr.Column(scale=3):
                        gr.Markdown("### Upload a Chinese video\n"
                                    "Any common format: mp4, mkv, mov, avi… Long episodes (1 hour+) are fine.")
                        upload = gr.File(label="Chinese video  ·  វីដេអូចិន", file_types=["video"], type="filepath",
                                         height=170)
                        with gr.Row():
                            existing = gr.Dropdown(label="…or continue a saved project", choices=list_projects(),
                                                   value=None, scale=5)
                            refresh = gr.Button("↻ Refresh", scale=1, min_width=90)
                    with gr.Column(scale=2):
                        thumb = gr.Image(interactive=False, height=210, show_label=False)
                        card = gr.HTML('<div class="card"><h3>How it works</h3>'
                                       "1️⃣ Upload &nbsp;→&nbsp; 2️⃣ Choose settings &nbsp;→&nbsp; 3️⃣ Check the "
                                       "Khmer lines &nbsp;→&nbsp; 4️⃣ Blur &nbsp;→&nbsp; 5️⃣ Get your video"
                                       '<p class="hint">In a hurry? After uploading, press <b>Do everything '
                                       "automatically</b>.</p></div>")
                with gr.Row():
                    to_settings = gr.Button("Next: choose settings →", variant="primary", elem_classes="big-btn")
                    auto_all_1 = gr.Button("⚡ Do everything automatically", elem_classes="big-btn")

            # ------------------------------------------------------- 2 settings
            with gr.Tab("2 · Settings", id="settings"):
                preset = gr.Radio(label="Quick choice (sets the options below)", choices=PRESET_CHOICES, value="free")
                with gr.Row(equal_height=False):
                    with gr.Column():
                        with gr.Group():
                            gr.Markdown("#### 🌐 Translation  ·  ការបកប្រែ")
                            translator = gr.Dropdown(label="Translator", choices=[(v, k) for k, v in ENGINES.items()],
                                                     value="google")
                            translator_help = gr.Markdown(TRANSLATOR_HELP["google"], elem_classes="hint")
                            provider = gr.Dropdown(label="AI service",
                                                   choices=[("OpenRouter (free models)", "openrouter"),
                                                            ("Groq (free, fast)", "groq"),
                                                            ("DeepSeek (cheap, great at Chinese)", "deepseek"),
                                                            ("Ollama (on this computer)", "ollama"),
                                                            ("Other (paste address)", "other")],
                                                   value="openrouter", visible=False)
                            base_url = gr.Textbox(label="API address (base URL)", visible=False,
                                                  placeholder="https://…/v1")
                            api_key = gr.Textbox(label="API key", type="password", visible=False,
                                                 placeholder="Paste your key (it is not saved to disk)")
                            model = gr.Textbox(label="Model (optional)", visible=False, placeholder="default")
                        with gr.Group():
                            gr.Markdown("#### 🗣 Khmer voice  ·  សំឡេងខ្មែរ")
                            voice_mode = gr.Radio(label="Who speaks",
                                                  choices=[("Automatic: woman → Sreymom, man → Piseth", "auto"),
                                                           ("Only Sreymom 👩", "sreymom"), ("Only Piseth 👨", "piseth")],
                                                  value="auto")
                            with gr.Row():
                                voice_speed = gr.Slider(-30, 30, value=0, step=5, label="Speaking speed (%)",
                                                        info="+ faster, − slower")
                                voice_pitch = gr.Slider(-20, 20, value=0, step=2, label="Voice pitch (Hz)",
                                                        info="+ higher, − deeper")
                            remove_voice = gr.Checkbox(label="Remove the Chinese voice (keep music & sound effects)",
                                                       value=True)
                    with gr.Column():
                        with gr.Group():
                            gr.Markdown("#### 💬 Khmer subtitles  ·  អក្សររត់ខ្មែរ")
                            subtitles = gr.Radio(label="Subtitles",
                                                 choices=[("In the picture", "burn"),
                                                          ("Separate (viewer can turn off)", "soft"), ("None", "none")],
                                                 value="burn")
                            with gr.Row():
                                subtitle_position = gr.Radio(label="Position", choices=[("Bottom", "bottom"),
                                                                                       ("Top", "top")], value="bottom")
                                subtitle_color = gr.Radio(label="Colour", choices=[("White", "white"),
                                                                                  ("Yellow", "yellow")], value="white")
                            with gr.Row():
                                subtitle_size = gr.Slider(0.6, 1.8, value=1.0, step=0.05, label="Size")
                                subtitle_box = gr.Checkbox(label="Dark box behind text", value=False)
                        with gr.Group():
                            gr.Markdown("#### 🫥 Blur Chinese text  ·  បិទអក្សរចិន")
                            blur = gr.Radio(label="Automatic blur",
                                            choices=[("Chinese text only", "chinese"), ("All text", "all"),
                                                     ("Off", "off")], value="chinese")
                            with gr.Row():
                                blur_style = gr.Radio(label="Look", choices=[("Blur", "blur"), ("Pixels", "pixelate"),
                                                                            ("Dark box", "box")], value="blur")
                                blur_sample_fps = gr.Radio(label="Scan", choices=[("Fast", 2.0), ("Normal", 3.0),
                                                                                 ("Careful", 5.0)], value=3.0,
                                                           info="Careful = better for fast-moving text")
                with gr.Accordion("More options", open=False):
                    with gr.Row():
                        whisper_model = gr.Dropdown(label="Speech recognition",
                                                    choices=[("Auto (best for this computer)", "auto"),
                                                             ("small: fastest", "small"), ("medium", "medium"),
                                                             ("large-v3-turbo: best with GPU", "large-v3-turbo"),
                                                             ("large-v3: most accurate, slowest", "large-v3")],
                                                    value="auto")
                        video_quality = gr.Radio(label="Video quality", choices=[("Fast", "fast"), ("Balanced", "balanced"),
                                                                                ("High", "high")], value="balanced")
                        resolution = gr.Dropdown(label="Output size", choices=[("Same as original", "original"),
                                                                             ("1080p", "1080"), ("720p (smaller file)", "720"),
                                                                             ("480p (smallest)", "480")], value="original")
                    with gr.Row():
                        max_speedup = gr.Slider(1.0, 2.0, value=1.5, step=0.05, label="Max speed-up to fit timing",
                                                info="Khmer is often longer than Chinese; lines are sped up at most this much")
                        background_volume = gr.Slider(0, 2, value=1.0, step=0.05, label="Music / effects volume")
                        dub_volume = gr.Slider(0.2, 2, value=1.0, step=0.05, label="Khmer voice volume")
                    keep_original_audio = gr.Checkbox(label="Also keep the original Chinese sound as a 2nd audio track",
                                                      value=False)
                    gr.Markdown("**Already have subtitles?** Skip speech recognition (Chinese .srt) or skip both "
                                "transcript and translation (Khmer .srt).", elem_classes="hint")
                    with gr.Row():
                        zh_srt = gr.File(label="Chinese .srt (optional)", file_types=[".srt"], type="filepath", height=90)
                        km_srt = gr.File(label="Khmer .srt (optional)", file_types=[".srt"], type="filepath", height=90)
                with gr.Row():
                    start_prepare = gr.Button("▶ Start: make transcript & Khmer translation", variant="primary",
                                              elem_classes="big-btn")
                    auto_all_2 = gr.Button("⚡ Do everything automatically", elem_classes="big-btn")
                prep_msg = gr.Markdown("")

            # ------------------------------------------------------- 3 review
            with gr.Tab("3 · Review", id="review"):
                gr.Markdown("**Check the Khmer lines.** Click a line to edit it, listen to it, or change the voice. "
                            "Press *Save* or *Save & next* to keep a change.  "
                            "<span class='hint'>ចុចលើបន្ទាត់ ដើម្បីកែ</span>")
                with gr.Row(equal_height=False):
                    with gr.Column(scale=3):
                        table = gr.Dataframe(headers=TABLE_HEADERS, datatype=["number", "str", "str", "str", "str"],
                                             type="array", interactive=False, wrap=True, max_height=560,
                                             column_widths=["5%", "9%", "33%", "38%", "15%"], elem_classes="khmer",
                                             show_label=False)
                    with gr.Column(scale=2):
                        with gr.Group():
                            line_title = gr.Markdown("#### Pick a line on the left")
                            zh_text = gr.Textbox(label="Chinese (original)", interactive=False, lines=2)
                            km_text = gr.Textbox(label="Khmer  ·  ខ្មែរ", lines=3, elem_classes="khmer")
                            line_voice = gr.Radio(label="Voice", choices=[("👩 Sreymom", "sreymom"),
                                                                         ("👨 Piseth", "piseth")], value="sreymom")
                            with gr.Row():
                                play_zh = gr.Button("🔊 Original")
                                play_km = gr.Button("🔊 Khmer voice")
                            line_audio = gr.Audio(type="filepath", autoplay=True, interactive=False, show_label=False)
                            with gr.Row():
                                prev_line = gr.Button("◀ Previous")
                                save_line = gr.Button("💾 Save")
                                next_line = gr.Button("Save & next ▶", variant="primary")
                        with gr.Accordion("Tools for all lines", open=False):
                            with gr.Row():
                                find_txt = gr.Textbox(label="Find (Khmer)", elem_classes="khmer")
                                repl_txt = gr.Textbox(label="Replace with", elem_classes="khmer")
                            replace_btn = gr.Button("Replace in every line")
                            gr.Markdown("Tip: use this to spell a character's name the same way everywhere.",
                                        elem_classes="hint")
                            with gr.Row():
                                all_sreymom = gr.Button("All lines → Sreymom")
                                all_piseth = gr.Button("All lines → Piseth")
                            retranslate = gr.Button("🔁 Translate everything again (with the translator from tab 2)")
                to_blur = gr.Button("Next: check the blur →", variant="primary", elem_classes="big-btn")

            # ------------------------------------------------------- 4 blur
            with gr.Tab("4 · Blur", id="blur") as blur_tab:
                gr.Markdown("The app finds and blurs Chinese text by itself: subtitles, logos and moving text. "
                            "Use this page to **check** it and to **add boxes** for anything it misses.")
                with gr.Row(equal_height=False):
                    with gr.Column(scale=3):
                        blur_t = gr.Slider(0, 60, value=5, step=0.5, label="Move through the video (seconds)")
                        blur_img = gr.Image(label="🟩 found automatically · 🟧 your boxes", interactive=False,
                                            height=440)
                        gr.Markdown("**Add a box:** click the **top-left** corner of the text, then the "
                                    "**bottom-right** corner.", elem_classes="hint")
                    with gr.Column(scale=2):
                        scan_btn = gr.Button("🔍 Scan the whole video for Chinese text now")
                        scan_msg = gr.Markdown("", elem_classes="hint")
                        box_whole = gr.Checkbox(label="New boxes cover the whole video", value=True)
                        with gr.Row():
                            box_from = gr.Number(label="…or only from (s)", value=None)
                            box_to = gr.Number(label="to (s)", value=None)
                        box_table = gr.Dataframe(headers=["x %", "y %", "w %", "h %", "from", "to"],
                                                 type="array", interactive=False, label="Your boxes", max_height=180)
                        with gr.Row():
                            undo_box = gr.Button("Remove last box")
                            clear_box = gr.Button("Remove all")
                        preview_btn = gr.Button("🎬 Preview 20 seconds from here")
                        preview_vid = gr.Video(label="Preview", interactive=False, height=240)
                to_export = gr.Button("Next: make the video →", variant="primary", elem_classes="big-btn")

            # ------------------------------------------------------- 5 export
            with gr.Tab("5 · Export", id="export"):
                with gr.Row(equal_height=False):
                    with gr.Column(scale=3):
                        make_btn = gr.Button("🎬 Make the Khmer video  ·  បង្កើតវីដេអូខ្មែរ", variant="primary",
                                             elem_classes="big-btn")
                        result = gr.Video(label="Khmer video", interactive=False, height=420)
                    with gr.Column(scale=2):
                        downloads = gr.File(label="Downloads", file_count="multiple", interactive=False)
                        gr.Markdown("**You get:** the video (.mp4), Khmer subtitles (.srt) for YouTube/Facebook, "
                                    "the Khmer soundtrack (.m4a) and the Chinese transcript.", elem_classes="hint")
                        folder = gr.Textbox(label="Project folder on this computer", interactive=False)
                with gr.Accordion("Details / log", open=False):
                    log_box = gr.Textbox(lines=12, max_lines=30, autoscroll=True, show_label=False)

            # ------------------------------------------------------- batch
            with gr.Tab("Batch", id="batch"):
                gr.Markdown("### Many episodes at once\nAdd several videos. Each one is processed **automatically** "
                            "with the settings from tab 2 (no review step), one after another. "
                            "Good for a whole series overnight.")
                batch_files = gr.File(label="Videos", file_count="multiple", file_types=["video"], type="filepath")
                batch_btn = gr.Button("▶ Process all", variant="primary", elem_classes="big-btn")
                batch_table = gr.Dataframe(headers=["Video", "Status"], type="array", interactive=False)
                batch_out = gr.File(label="Finished videos", file_count="multiple", interactive=False)

            # ------------------------------------------------------- help
            with gr.Tab("Help", id="help"):
                gr.Markdown(HELP_MD)

        # =================================================== event handlers ====
        comp = dict(zip(SETTING_FIELDS, [
            translator, provider, base_url, model, whisper_model, voice_mode, voice_speed, voice_pitch, remove_voice,
            max_speedup, background_volume, dub_volume, subtitles, subtitle_size, subtitle_position, subtitle_color,
            subtitle_box, blur, blur_style, blur_sample_fps, video_quality, resolution, keep_original_audio]))
        setting_comps = list(comp.values())

        def settings_from(d, proj: Project, box_list=None) -> Settings:
            """Read every setting component, save them in the project and return Settings."""
            s = proj.load_settings()
            for name, c in comp.items():
                v, cur = d[c], getattr(s, name)
                if isinstance(cur, bool):
                    v = bool(v)
                elif v is None:
                    v = cur
                else:
                    v = type(cur)(v)
                setattr(s, name, v)
            s.blur_regions = list(box_list if box_list is not None else (d.get(boxes) or []))
            proj.save_settings(s)
            return s

        def _translator_visibility(t, prov) -> dict:
            custom = t == "custom"
            needs_key = t in ("claude", "openai", "gemini") or (custom and prov != "ollama")
            placeholder = (PROVIDERS.get(prov, ("", "", "", ""))[2] if custom else DEFAULT_MODELS.get(t, "")) or "default"
            note = f"\n\n*{PROVIDERS[prov][3]}*" if custom and prov in PROVIDERS else ""
            return {
                translator_help: TRANSLATOR_HELP.get(t, "") + note,
                provider: gr.update(visible=custom),
                base_url: gr.update(visible=custom and prov == "other"),
                api_key: gr.update(visible=needs_key),
                model: gr.update(visible=t != "google", placeholder=placeholder),
            }

        vis_out = [translator_help, provider, base_url, api_key, model]

        # ---- upload / load a project
        def load_into_ui(proj: Project) -> dict:
            import cv2

            from .media import video_info

            s = proj.load_settings()
            info = video_info(proj.video)
            frame, _ = frame_at(proj, min(5.0, info.duration / 3))
            out = {
                proj_dir: str(proj.dir), status: status_html(proj), card: video_card(proj),
                thumb: cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) if frame is not None else None,
                table: table_rows(proj), boxes: s.blur_regions, box_table: _box_rows(s.blur_regions),
                blur_t: gr.update(maximum=max(1.0, round(info.duration, 1)), value=min(5.0, info.duration / 3)),
                folder: str(proj.dir), existing: gr.update(choices=list_projects(), value=proj.dir.name),
                result: str(proj.output_video) if proj.output_video.exists() else None,
                downloads: [str(p) for p in Pipeline(proj, s, log=lambda m: None).downloads()] or None,
            }
            out.update({c: getattr(s, name) for name, c in comp.items()})
            out.update(_translator_visibility(s.translator, s.translator_provider))
            return out

        load_out = [proj_dir, status, card, thumb, table, boxes, box_table, blur_t, folder, existing, result,
                    downloads, *setting_comps, *[c for c in vis_out if c not in setting_comps]]

        upload.upload(lambda p: load_into_ui(project_from_upload(p)) if p else {}, [upload], load_out)
        existing.select(lambda n: load_into_ui(project_from_dir(PROJECTS / n)) if n else {}, [existing], load_out)
        refresh.click(lambda: gr.update(choices=list_projects()), None, [existing])

        # ---- settings
        def on_preset(p):
            if p not in PRESETS:
                return {}
            out = {comp[k]: v for k, v in PRESETS[p].items()}
            out.update(_translator_visibility(PRESETS[p]["translator"], "openrouter"))
            return out

        preset.input(on_preset, [preset], list(dict.fromkeys([*setting_comps, *vis_out])))
        translator.change(_translator_visibility, [translator, provider], vis_out)
        provider.change(_translator_visibility, [translator, provider], vis_out)

        # ---- step 1: transcript + translation
        def _prepare(d, progress, retrans=False):
            proj = project_from_dir(d[proj_dir])
            s = settings_from(d, proj)
            key = d.get(api_key) or None
            zh, km = d.get(zh_srt), d.get(km_srt)

            def work(log, prog):
                return Pipeline(proj, s, key, log, prog).prepare(Path(zh) if zh else None,
                                                                Path(km) if km else None, retrans)

            text = ""
            for text, msg, _done, _res, err in run_in_background(work, progress):
                yield {status: status_html(proj, msg), log_box: text, prep_msg: f"⏳ {msg}"}
            if err:
                yield {status: status_html(proj), prep_msg: f"❌ **{_friendly(err)}**", log_box: text}
                raise gr.Error(_friendly(err))
            yield {status: status_html(proj), table: table_rows(proj), log_box: text,
                   prep_msg: "✅ Done! Now check the lines in **3 · Review**.", tabs: gr.Tabs(selected="review")}

        prep_in = {proj_dir, api_key, zh_srt, km_srt, boxes, *setting_comps}
        prep_out = [status, table, log_box, prep_msg, tabs]

        def do_prepare(d, progress=gr.Progress()):
            yield from _prepare(d, progress)

        def do_retranslate(d, progress=gr.Progress()):
            yield from _prepare(d, progress, retrans=True)

        start_prepare.click(do_prepare, prep_in, prep_out, show_progress_on=[prep_msg])
        retranslate.click(do_retranslate, prep_in, prep_out, show_progress_on=[table])
        to_settings.click(lambda: gr.Tabs(selected="settings"), None, [tabs])

        # ---- everything automatically
        def do_all(d, progress=gr.Progress()):
            proj = project_from_dir(d[proj_dir])
            s = settings_from(d, proj)
            key = d.get(api_key) or None
            zh, km = d.get(zh_srt), d.get(km_srt)

            def work(log, prog):
                return Pipeline(proj, s, key, log, prog).run_all(Path(zh) if zh else None, Path(km) if km else None)

            text, res, first = "", None, True
            for text, msg, _done, res, err in run_in_background(work, progress):
                out = {status: status_html(proj, msg), log_box: text}
                if first:
                    out[tabs], first = gr.Tabs(selected="export"), False
                yield out
            if err:
                yield {status: status_html(proj), log_box: text}
                raise gr.Error(_friendly(err))
            gr.Info("Your Khmer video is ready! 🎉")
            yield {status: status_html(proj), log_box: text, table: table_rows(proj), result: str(res),
                   downloads: [str(p) for p in Pipeline(proj, s, log=lambda m: None).downloads()]}

        auto_out = [status, log_box, tabs, table, result, downloads]
        auto_all_1.click(do_all, prep_in, auto_out, show_progress_on=[result])
        auto_all_2.click(do_all, prep_in, auto_out, show_progress_on=[result])

        # ---- review: line editor
        def show_line(proj_v, idx) -> dict:
            proj = project_from_dir(proj_v)
            segs = proj.load_segments() if proj.has_segments() else []
            if not segs:
                return {line_title: "#### No lines yet. Press Start in tab 2 first."}
            idx = max(0, min(int(idx), len(segs) - 1))
            sg = segs[idx]
            return {line_idx: idx,
                    line_title: f"#### Line {idx + 1} / {len(segs)}  ·  {fmt_t(sg.start)} → {fmt_t(sg.end)}",
                    zh_text: sg.zh, km_text: sg.km, line_voice: sg.voice, line_audio: None}

        line_out = [line_idx, line_title, zh_text, km_text, line_voice, line_audio]

        def on_table_select(proj_v, evt: gr.SelectData):
            return show_line(proj_v, evt.index[0])

        table.select(on_table_select, [proj_dir], line_out)

        def _save_current(proj_v, idx, km, voice) -> Project:
            proj = project_from_dir(proj_v)
            segs = proj.load_segments() if proj.has_segments() else []
            if segs:
                sg = segs[max(0, min(int(idx), len(segs) - 1))]
                sg.km, sg.voice = (km or "").strip(), voice
                proj.save_segments(segs)
                # remember that voices are now hand-picked, so they aren't re-guessed
                proj.path("voices_mode.txt").write_text(proj.load_settings().voice_mode)
            return proj

        def do_save(proj_v, idx, km, voice):
            proj = _save_current(proj_v, idx, km, voice)
            gr.Info("Saved")
            return table_rows(proj), status_html(proj)

        def do_step(proj_v, idx, km, voice, delta, save):
            proj = _save_current(proj_v, idx, km, voice) if save else project_from_dir(proj_v)
            out = show_line(proj_v, int(idx) + delta)
            out[table] = table_rows(proj)
            return out

        edit_in = [proj_dir, line_idx, km_text, line_voice]
        save_line.click(do_save, edit_in, [table, status])
        next_line.click(lambda *a: do_step(*a, 1, True), edit_in, [*line_out, table])
        prev_line.click(lambda *a: do_step(*a, -1, False), edit_in, [*line_out, table])

        def do_play_zh(proj_v, idx):
            proj = project_from_dir(proj_v)
            segs = proj.load_segments()
            return str(Pipeline(proj, log=lambda m: None).line_original_audio(segs[int(idx)]))

        def do_play_km(proj_v, km, voice):
            if not (km or "").strip():
                raise gr.Error("This line has no Khmer text yet.")
            proj = project_from_dir(proj_v)
            try:
                return str(Pipeline(proj, log=lambda m: None).line_khmer_audio(km, voice))
            except Exception as e:
                raise gr.Error(_friendly(e)) from e

        play_zh.click(do_play_zh, [proj_dir, line_idx], [line_audio])
        play_km.click(do_play_km, [proj_dir, km_text, line_voice], [line_audio], show_progress_on=[line_audio])

        def do_replace(proj_v, find, repl):
            if not find:
                raise gr.Error("Type the text to find.")
            proj = project_from_dir(proj_v)
            segs = proj.load_segments()
            n = 0
            for sg in segs:
                if find in sg.km:
                    sg.km, n = sg.km.replace(find, repl or ""), n + 1
            proj.save_segments(segs)
            gr.Info(f"Changed {n} lines")
            return table_rows(proj)

        replace_btn.click(do_replace, [proj_dir, find_txt, repl_txt], [table])

        def do_all_voice(proj_v, v):
            proj = project_from_dir(proj_v)
            segs = proj.load_segments()
            for sg in segs:
                sg.voice = v
            proj.save_segments(segs)
            proj.path("voices_mode.txt").write_text(proj.load_settings().voice_mode)
            return table_rows(proj)

        all_sreymom.click(lambda p: do_all_voice(p, "sreymom"), [proj_dir], [table])
        all_piseth.click(lambda p: do_all_voice(p, "piseth"), [proj_dir], [table])

        # ---- blur page
        def draw_blur_frame(proj_v, t, box_list, pt, blur_mode, fps):
            import cv2

            from . import blur as blurmod

            if not proj_v:
                return None
            proj = project_from_dir(proj_v)
            t = float(t or 0)
            frame, scale = frame_at(proj, t)
            if frame is None:
                return None
            H, W = frame.shape[:2]
            cache = proj.path(f"blur_{blur_mode}_{float(fps):g}fps.json")
            if cache.exists():
                for x0, y0, x1, y1 in blurmod.Timeline(blurmod.load_tracks(cache)).boxes(t):
                    cv2.rectangle(frame, (int(x0 * scale), int(y0 * scale)), (int(x1 * scale), int(y1 * scale)),
                                  (60, 200, 60), 2)
            for r in box_list or []:
                a, b = r.get("start"), r.get("end")
                active = a is None or b is None or a <= t <= b
                cv2.rectangle(frame, (int(r["x"] * W), int(r["y"] * H)),
                              (int((r["x"] + r["w"]) * W), int((r["y"] + r["h"]) * H)),
                              (0, 140, 255) if active else (130, 130, 130), 3)
            if pt:
                cv2.drawMarker(frame, (int(pt[0] * W), int(pt[1] * H)), (0, 140, 255), cv2.MARKER_CROSS, 26, 3)
            return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        blur_view_in = [proj_dir, blur_t, boxes, pending_pt, blur, blur_sample_fps]
        blur_t.release(draw_blur_frame, blur_view_in, [blur_img])
        blur_tab.select(draw_blur_frame, blur_view_in, [blur_img])

        def go_blur(*a):
            return gr.Tabs(selected="blur"), draw_blur_frame(*a)

        to_blur.click(go_blur, blur_view_in, [tabs, blur_img])

        def on_img_click(proj_v, t, box_list, pt, whole, a, b, blur_mode, fps, evt: gr.SelectData):
            proj = project_from_dir(proj_v)
            frame, _ = frame_at(proj, float(t or 0))
            H, W = frame.shape[:2]
            x, y = evt.index[0] / W, evt.index[1] / H
            box_list = list(box_list or [])
            if pt is None:
                pt, msg = [x, y], "Now click the bottom-right corner of the text."
            else:
                x0, y0, x1, y1 = min(pt[0], x), min(pt[1], y), max(pt[0], x), max(pt[1], y)
                if (x1 - x0) > 0.005 and (y1 - y0) > 0.005:
                    box = {"x": round(x0, 4), "y": round(y0, 4), "w": round(x1 - x0, 4), "h": round(y1 - y0, 4)}
                    if not whole and a not in (None, "") and b not in (None, "") and float(b) > float(a):
                        box["start"], box["end"] = float(a), float(b)
                    box_list.append(box)
                    _save_boxes(proj, box_list)
                pt, msg = None, f"Box added ({len(box_list)} in total)."
            gr.Info(msg)
            return {boxes: box_list, pending_pt: pt, box_table: _box_rows(box_list),
                    blur_img: draw_blur_frame(proj_v, t, box_list, pt, blur_mode, fps)}

        blur_img.select(on_img_click, [proj_dir, blur_t, boxes, pending_pt, box_whole, box_from, box_to, blur,
                                       blur_sample_fps], [boxes, pending_pt, box_table, blur_img])

        def change_boxes(proj_v, t, box_list, blur_mode, fps, how):
            proj = project_from_dir(proj_v)
            box_list = [] if how == "clear" else list(box_list or [])[:-1]
            _save_boxes(proj, box_list)
            return box_list, _box_rows(box_list), None, draw_blur_frame(proj_v, t, box_list, None, blur_mode, fps)

        box_in = [proj_dir, blur_t, boxes, blur, blur_sample_fps]
        box_out = [boxes, box_table, pending_pt, blur_img]
        undo_box.click(lambda *a: change_boxes(*a, "undo"), box_in, box_out)
        clear_box.click(lambda *a: change_boxes(*a, "clear"), box_in, box_out)

        def do_scan(d, progress=gr.Progress()):
            proj = project_from_dir(d[proj_dir])
            s = settings_from(d, proj)
            if s.blur == "off":
                yield {scan_msg: "Automatic blur is **off** (tab 2). Only your own boxes will be used."}
                return

            def work(log, prog):
                return Pipeline(proj, s, None, log, prog).scan_text(prog)

            res = []
            for text, msg, _done, res, err in run_in_background(work, progress):
                yield {scan_msg: f"⏳ {msg}", status: status_html(proj, msg), log_box: text}
            if err:
                raise gr.Error(_friendly(err))
            n_move = sum(1 for tr in res if not tr["static"])
            yield {scan_msg: f"✅ Found **{len(res)}** pieces of Chinese text ({n_move} moving). "
                             "Move the slider to check them (green boxes).",
                   status: status_html(proj),
                   blur_img: draw_blur_frame(d[proj_dir], d[blur_t], d[boxes], None, d[blur], d[blur_sample_fps])}

        scan_in = {proj_dir, blur_t, boxes, *setting_comps}
        scan_btn.click(do_scan, scan_in, [scan_msg, status, log_box, blur_img], show_progress_on=[blur_img])

        def do_preview(d, progress=gr.Progress()):
            proj = project_from_dir(d[proj_dir])
            s = settings_from(d, proj)

            def work(log, prog):
                return Pipeline(proj, s, None, log, prog).preview(float(d[blur_t] or 0))

            text, res = "", None
            for text, msg, _done, res, err in run_in_background(work, progress):
                yield {log_box: text, scan_msg: f"⏳ {msg}"}
            if err:
                raise gr.Error(_friendly(err))
            yield {preview_vid: str(res), log_box: text, scan_msg: ""}

        preview_btn.click(do_preview, scan_in, [preview_vid, log_box, scan_msg], show_progress_on=[preview_vid])
        to_export.click(lambda: gr.Tabs(selected="export"), None, [tabs])

        # ---- export
        def do_make(d, progress=gr.Progress()):
            proj = project_from_dir(d[proj_dir])
            if not proj.has_segments():
                raise gr.Error("There is no translation yet. Go to tab 2 and press Start (or Do everything).")
            s = settings_from(d, proj)

            def work(log, prog):
                return Pipeline(proj, s, None, log, prog).produce()

            text, res = "", None
            for text, msg, _done, res, err in run_in_background(work, progress):
                yield {status: status_html(proj, msg), log_box: text}
            if err:
                yield {status: status_html(proj), log_box: text}
                raise gr.Error(_friendly(err))
            gr.Info("Your Khmer video is ready! 🎉")
            yield {status: status_html(proj), log_box: text, result: str(res),
                   downloads: [str(p) for p in Pipeline(proj, s, log=lambda m: None).downloads()],
                   folder: str(proj.dir)}

        make_btn.click(do_make, {proj_dir, boxes, *setting_comps}, [status, log_box, result, downloads, folder],
                       show_progress_on=[result])

        # ---- batch
        def do_batch(d, progress=gr.Progress()):
            files = d.get(batch_files) or []
            if not files:
                raise gr.Error("Add one or more videos first.")
            rows = [[Path(f).name, "waiting"] for f in files]
            finished: list[str] = []
            key = d.get(api_key) or None

            def work(log, prog):
                for i, f in enumerate(files):
                    rows[i][1] = "⏳ working"
                    try:
                        proj = project_from_upload(f)
                        s = settings_from(d, proj, [])

                        def p(fr, m, i=i):
                            prog((i + fr) / len(files), f"{i + 1}/{len(files)}: {m}")

                        finished.append(str(Pipeline(proj, s, key, log, p).run_all()))
                        rows[i][1] = "✅ done"
                    except Exception as e:  # keep going with the next episode
                        rows[i][1] = f"❌ {_friendly(e)[:120]}"
                        log(f"{Path(f).name}: {e}")
                return finished

            text = ""
            for text, _msg, _done, _res, _err in run_in_background(work, progress):
                yield {batch_table: [r[:] for r in rows], log_box: text}
            yield {batch_table: rows, batch_out: finished or None, log_box: text,
                   existing: gr.update(choices=list_projects())}

        batch_btn.click(do_batch, {batch_files, api_key, boxes, *setting_comps},
                        [batch_table, batch_out, log_box, existing], show_progress_on=[batch_table])

        # ---- simple API for scripts: one call, video in -> Khmer video + subtitles out
        def api_dub(video, translator_name="google", key="", voice="auto", blur_mode="chinese",
                    subs="burn"):
            proj = project_from_upload(video)
            s = proj.load_settings()
            s.translator, s.voice_mode, s.blur, s.subtitles = translator_name, voice, blur_mode, subs
            proj.save_settings(s)
            out = Pipeline(proj, s, key or None, log=lambda m: None).run_all()
            srt = proj.path(f"{proj.video.stem}_khmer.srt")
            return str(out), str(srt) if srt.exists() else None

        with gr.Row(visible=False):
            a_video = gr.File(type="filepath")
            a_tr, a_key, a_voice = gr.Textbox("google"), gr.Textbox(""), gr.Textbox("auto")
            a_blur, a_subs = gr.Textbox("chinese"), gr.Textbox("burn")
            a_out_v, a_out_s = gr.File(), gr.File()
            a_btn = gr.Button()
        a_btn.click(api_dub, [a_video, a_tr, a_key, a_voice, a_blur, a_subs], [a_out_v, a_out_s],
                    api_name="dub_video")

    return app


HELP_MD = """
## How to use  ·  របៀបប្រើ

1. **Upload** a Chinese video in tab 1 (or continue a saved project).
2. **Settings** (tab 2): the quick choices at the top are enough for most videos. Press **Start**.
3. **Review** (tab 3): click any line to fix the Khmer, listen to it, or switch between Sreymom 👩 and Piseth 👨.
4. **Blur** (tab 4): check that the Chinese text is covered; click two corners to add a box.
5. **Export** (tab 5): press **Make the Khmer video** and download the result.

Everything is saved in the `projects` folder, so you can stop and continue later.
After you change a line, only that line's voice is made again.

## Which translator should I use?

| | Cost | Quality |
|---|---|---|
| Google Translate | free, no key | OK |
| Gemini | free key | good |
| OpenRouter / Groq | free key | good (depends on the model) |
| DeepSeek | very cheap key | good |
| Claude | paid key (cents per episode) | best |
| Ollama | free, runs on your computer | depends on your PC |
| NLLB offline | free | basic |

## Tips

- **Long videos (1 hour):** use *Do everything automatically* or the **Batch** tab and let it run.
  Without a GPU it takes roughly 1.5–2× the length of the video.
- **Wrong voice on some lines?** Fix them in Review, or choose *Only Sreymom* / *Only Piseth*.
- **Same name translated differently?** Use *Find → Replace* in Review → Tools for all lines.
- **Khmer voice too fast?** Lower *Max speed-up* or the speaking speed in Settings.
- **Some Chinese text isn't blurred?** Set Scan to *Careful*, or add a box in tab 4.

## For developers

Use the app from your own scripts while it is running (also see *Use via API* at the bottom of the page):

```python
from gradio_client import Client, handle_file

client = Client("http://localhost:7860/")
video, srt = client.predict(
    handle_file("episode01.mp4"),   # Chinese video
    "google",                       # translator: google, gemini, claude, openai, custom, nllb
    "",                             # API key (if the translator needs one)
    "auto",                         # voice: auto, sreymom, piseth
    "chinese",                      # blur: chinese, all, off
    "burn",                         # subtitles: burn, soft, none
    api_name="/dub_video",
)
```

There is also a command line: `uv run --extra cpu khmerdub run video.mp4 --help`.
"""


def launch(port: int = 7860, share: bool = False, projects_dir: str | None = None,
           inbrowser: bool = True) -> None:
    global PROJECTS
    if projects_dir:
        PROJECTS = Path(projects_dir)
    PROJECTS.mkdir(parents=True, exist_ok=True)
    PROJECTS = PROJECTS.resolve()
    theme = gr.themes.Soft(
        primary_hue="indigo", secondary_hue="amber", radius_size="lg",
        font=[gr.themes.GoogleFont("Kantumruy Pro"), "Noto Sans Khmer", "ui-sans-serif", "sans-serif"],
    )
    app = build_app()
    app.queue(default_concurrency_limit=1).launch(
        server_port=port, share=share, inbrowser=inbrowser, allowed_paths=[str(PROJECTS)],
        theme=theme, css=CSS, max_file_size="20gb",
    )
