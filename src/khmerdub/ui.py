"""Web app: a step-by-step Chinese → Khmer dubbing studio (Gradio).

Visual world: Hol silk (Khmer ikat). An indigo-dyed shell; lac red = Sreymom, dyed blue = Piseth,
turmeric = the current line and the next action, jade = done. The episode is drawn on the Review
step as a weft band: one block per line, as wide as the line is long.

Steps: Upload · Settings · Review · Blur · Export, plus Cut, Batch and Help.
"""

from __future__ import annotations

import html
import re
import shutil
import threading
import time
import traceback
from pathlib import Path

import gradio as gr

from . import __version__, jobs
from .project import Project, Settings
from .translate import DEFAULT_MODELS, ENGINES, PROVIDERS

PROJECTS = Path("projects")
FONTS = Path(__file__).parent / "fonts"

# ----------------------------------------------------------------- palette ----
GROUND, PANEL, RAIL, RAISED = "#10143a", "#161b45", "#1b2147", "#262e5e"
RULE, RULE_L = "#343c74", "#4a5290"
SILK, SILK_2, SILK_3 = "#f1e8d6", "#bdbdd6", "#9396bb"
TUR, TUR_L, TUR_INK = "#e8a62a", "#f2b94a", "#1a1203"
LAC, LAC_T = "#c9384d", "#f07386"  # Sreymom: dye / text on indigo
SKY, SKY_T = "#5f80e6", "#93abff"  # Piseth
JADE = "#3aa883"

STEPS = [("upload", "Upload"), ("settings", "Settings"), ("review", "Review"), ("blur", "Blur"),
         ("export", "Export")]
EXTRAS = [("cut", "Cut"), ("batch", "Batch"), ("help", "Help")]

# Settings field names, in the same order as the components passed to `comp` in build_app().
SETTING_FIELDS = [
    "translator", "translator_provider", "translator_base_url", "translator_model", "whisper_model",
    "voice_mode", "voice_speed", "voice_pitch", "remove_voice", "max_speedup", "fit_mode", "background_volume",
    "dub_volume",
    "subtitles", "subtitle_size", "subtitle_position", "subtitle_color", "subtitle_box",
    "blur", "blur_style", "blur_sample_fps", "video_quality", "resolution", "keep_original_audio",
]

PRESETS = {
    "free": {"translator": "google", "whisper_model": "auto", "blur_sample_fps": 3.0, "video_quality": "balanced"},
    "gemini": {"translator": "gemini", "whisper_model": "auto", "blur_sample_fps": 3.0, "video_quality": "balanced"},
    "best": {"translator": "claude", "whisper_model": "auto", "blur_sample_fps": 5.0, "video_quality": "high"},
    "fastest": {"translator": "google", "whisper_model": "small", "blur_sample_fps": 2.0, "video_quality": "fast"},
}
PRESET_CHOICES = [("Free · Google", "free"), ("Free AI · Gemini", "gemini"), ("Best · Claude", "best"),
                  ("Fastest", "fastest"), ("Custom", "custom")]

TRANSLATOR_HELP = {
    "google": "Free, no account. Literal, line by line. Good for a first try.",
    "gemini": "Free key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). "
              "Reads the story, keeps names consistent.",
    "claude": "Most natural spoken Khmer. Paid key from [console.anthropic.com](https://console.anthropic.com), "
              "a few cents per episode.",
    "openai": "Paid key from [platform.openai.com](https://platform.openai.com).",
    "custom": "OpenRouter and Groq have free keys, DeepSeek is cheap, Ollama runs on this computer.",
    "nllb": "Runs here, no internet or key. Needs `uv sync --extra cpu --extra offline` once; basic quality.",
}


SPEED_CHOICES = [("Speed: auto", "auto"), ("Speed 0.85×", "-15"), ("Speed 0.9×", "-10"), ("Speed 1.0×", "0"),
                 ("Speed 1.1×", "10"), ("Speed 1.2×", "20"), ("Speed 1.3×", "30"), ("Speed 1.4×", "40"),
                 ("Speed 1.5×", "50")]


def fit_text(info: dict | None) -> str:
    """Short words for how a line's Khmer voice fits the character."""
    if not info:
        return "—"
    st = info.get("status", "none")
    return {"ok": "fits", "fast": f"×{info.get('factor', 1):.2f}".rstrip("0").rstrip("."),
            "late": f"{info.get('late', 0):.1f} s late", "long": f"{info.get('off', 0):.1f} s long",
            "short": f"{-info.get('off', 0):.1f} s short", "changed": "changed", "none": "—",
            "silent": "no speech", "novoice": "no voice yet"}.get(st, "—")


PROBLEM = {"late", "long", "novoice"}
TO_FIX = {"late", "long", "short", "fast", "changed", "novoice"}


def _report(proj: Project | None) -> dict:
    if proj is None or not proj.has_segments():
        return {"made": False, "lines": {}, "counts": {}}
    from .pipeline import Pipeline

    return Pipeline(proj, log=lambda m: None).fit_report()


def sync_html(proj: Project | None, rep: dict | None = None) -> str:
    if proj is None or not proj.has_segments():
        return '<div class="kd-syncline">Make the Khmer voices to check how each line fits the character.</div>'
    rep = rep or _report(proj)
    if not rep["made"]:
        return ('<div class="kd-syncline">Timing not checked yet. <b>Check timing</b> makes the Khmer voices and '
                'shows which lines start and end with the character.</div>')
    c = rep["counts"]
    parts = [f'<span class="ok">{c["ok"]} fit</span>']
    if c["fast"]:
        parts.append(f'<span>{c["fast"]} faster</span>')
    if c["short"]:
        parts.append(f'<span>{c["short"]} end early</span>')
    if c["long"] or c["late"]:
        parts.append(f'<span class="bad">{c["long"] + c["late"]} run over</span>')
    if c.get("novoice"):
        parts.append(f'<span class="bad">{c["novoice"]} without voice</span>')
    if c["changed"]:
        parts.append(f'<span class="dim">{c["changed"]} changed since</span>')
    return f'<div class="kd-syncline">Timing: {" · ".join(parts)}</div>'


# =========================================================== theme & css ======
def hol_theme() -> gr.themes.Base:
    indigo = gr.themes.Color(c50="#eceaf3", c100="#d9d8e8", c200="#b8b9d4", c300="#9497bd", c400="#6f73a3",
                             c500="#4f5488", c600="#3a4174", c700="#2a3166", c800="#1b2147", c900="#161b45",
                             c950="#10143a", name="indigo-dye")
    turmeric = gr.themes.Color(c50="#fdf6e7", c100="#fbe9c2", c200="#f6d48a", c300="#f0bd52", c400="#eaa935",
                               c500="#e8a62a", c600="#c4841a", c700="#9c6614", c800="#744b11", c900="#4f330c",
                               c950="#2e1d07", name="turmeric")
    font = ["KD Kantumruy", "Kantumruy Pro", "KD Noto Khmer", "Noto Sans Khmer", "ui-sans-serif", "sans-serif"]
    t = gr.themes.Base(primary_hue=turmeric, secondary_hue=turmeric, neutral_hue=indigo, font=font,
                       font_mono=["ui-monospace", "monospace"], radius_size=gr.themes.sizes.radius_none,
                       text_size=gr.themes.sizes.text_md, spacing_size=gr.themes.sizes.spacing_md)
    none = "none"
    v = {
        "body_background_fill": GROUND, "body_text_color": SILK, "body_text_color_subdued": SILK_2,
        "background_fill_primary": PANEL, "background_fill_secondary": GROUND,
        "border_color_primary": RULE, "border_color_accent": TUR, "border_color_accent_subdued": RULE,
        "color_accent": TUR, "color_accent_soft": RAISED,
        "link_text_color": TUR, "link_text_color_hover": TUR_L, "link_text_color_visited": TUR,
        "link_text_color_active": TUR, "accordion_text_color": SILK, "table_text_color": SILK,
        "block_background_fill": PANEL, "block_border_color": RULE, "block_border_width": "1px",
        "block_label_background_fill": PANEL, "block_label_text_color": SILK_2, "block_label_border_color": RULE,
        "block_title_text_color": SILK_2, "block_info_text_color": SILK_3, "block_shadow": none,
        "block_label_shadow": none, "panel_background_fill": PANEL, "panel_border_color": RULE,
        "input_background_fill": GROUND, "input_background_fill_focus": GROUND, "input_background_fill_hover": GROUND,
        "input_border_color": RULE, "input_border_color_focus": TUR, "input_border_color_hover": RULE_L,
        "input_placeholder_color": SILK_3, "input_shadow": none, "input_shadow_focus": none,
        "button_primary_background_fill": TUR, "button_primary_background_fill_hover": TUR_L,
        "button_primary_text_color": TUR_INK, "button_primary_text_color_hover": TUR_INK,
        "button_primary_border_color": TUR, "button_primary_border_color_hover": TUR_L,
        "button_primary_shadow": none, "button_primary_shadow_hover": none, "button_primary_shadow_active": none,
        "button_secondary_background_fill": RAIL, "button_secondary_background_fill_hover": RAISED,
        "button_secondary_text_color": SILK, "button_secondary_text_color_hover": SILK,
        "button_secondary_border_color": RULE, "button_secondary_border_color_hover": RULE_L,
        "button_secondary_shadow": none, "button_secondary_shadow_hover": none, "button_secondary_shadow_active": none,
        "button_transform_hover": none, "button_transform_active": none,
        "checkbox_background_color": GROUND, "checkbox_background_color_selected": TUR,
        "checkbox_border_color": RULE_L, "checkbox_border_color_selected": TUR, "checkbox_border_color_focus": TUR,
        "checkbox_label_background_fill": RAIL, "checkbox_label_background_fill_hover": RAISED,
        "checkbox_label_background_fill_selected": RAISED, "checkbox_label_border_color": RULE,
        "checkbox_label_border_color_hover": RULE_L, "checkbox_label_border_color_selected": TUR,
        "checkbox_label_text_color": SILK, "checkbox_label_text_color_selected": SILK, "checkbox_shadow": none,
        "checkbox_label_shadow": none,
        "slider_color": TUR, "loader_color": TUR, "stat_background_fill": TUR, "code_background_fill": GROUND,
        "table_border_color": RULE, "table_even_background_fill": PANEL, "table_odd_background_fill": "#141943",
        "table_row_focus": RAISED,
        "error_background_fill": "#2c1230", "error_border_color": LAC, "error_text_color": "#ffc2cb",
        "error_icon_color": LAC_T,
        "shadow_drop": none, "shadow_drop_lg": none, "shadow_spread": "0px",
    }
    full = dict(v)
    full.update({k + "_dark": val for k, val in v.items() if hasattr(t, k + "_dark")})
    return t.set(**full)


def build_css() -> str:
    def url(name: str) -> str:
        return f"/gradio_api/file={(FONTS / name).resolve().as_posix()}"

    faces = f"""
@font-face {{ font-family: 'KD Kantumruy'; src: url('{url("KantumruyPro.ttf")}') format('truetype');
  font-weight: 100 900; font-display: swap; }}
@font-face {{ font-family: 'KD Moul'; src: url('{url("Moul-Regular.ttf")}') format('truetype'); font-display: swap; }}
@font-face {{ font-family: 'KD Noto Khmer'; src: url('{url("NotoSansKhmer-Regular.ttf")}') format('truetype');
  font-weight: 400; font-display: swap; }}
"""
    return faces + CSS


CSS = f"""
:root, .dark {{ color-scheme: dark; }}
body, gradio-app, .gradio-container {{ background: {GROUND} !important; }}
.gradio-container {{ max-width: none !important; padding: 0 !important; margin: 0 !important; }}
.gradio-container .main, .gradio-container .wrap, .gradio-container .contain {{ padding: 0 !important; max-width: none !important; }}
.gradio-container .contain > .column {{ gap: 0 !important; }}
::selection {{ background: {TUR}; color: {TUR_INK}; }}
* {{ scrollbar-color: {RULE_L} {GROUND}; scrollbar-width: thin; caret-color: {TUR}; }}
:focus-visible {{ outline: 2px solid {TUR} !important; outline-offset: 2px; }}
a {{ text-underline-offset: 3px; }}
footer {{ border-top: 1px solid {RULE}; opacity: .7; }}

/* ---- header: wordmark + project facts */
#kd-head {{ margin: 0 !important; padding: 0 !important; border: 0 !important; }}
#kd-head > div:not(.wrap), .kd-html > div:not(.wrap) {{ padding: 0 !important; margin: 0 !important; }}
.kd-head {{ display: grid; grid-template-columns: 232px 1fr; min-height: 80px; border-bottom: 1px solid {RULE};
  position: relative; }}
.kd-mark {{ background: {RAIL}; border-right: 1px solid {RULE}; padding: 16px 24px; display: flex;
  flex-direction: column; justify-content: center; gap: 2px; }}
.kd-mark b {{ font-size: 22px; font-weight: 700; letter-spacing: -0.01em; color: {SILK}; line-height: 1.1; }}
.kd-mark span {{ font-family: 'KD Moul', 'Moul', serif; font-size: 13px; color: {TUR}; line-height: 1.6; }}
.kd-proj {{ display: flex; align-items: center; gap: 24px; padding: 12px 32px; flex-wrap: wrap; }}
.kd-proj h1 {{ font-size: 22px; font-weight: 600; margin: 0; color: {SILK}; }}
.kd-proj .meta {{ font-size: 14px; color: {SILK_2}; font-variant-numeric: tabular-nums; }}
.kd-proj .empty {{ font-size: 15px; color: {SILK_2}; }}
.kd-counts {{ margin-left: auto; display: flex; gap: 0; }}
.kd-counts div {{ padding: 0 20px; border-left: 1px solid {RULE}; font-size: 12px; color: {SILK_2};
  letter-spacing: .04em; text-transform: uppercase; }}
.kd-counts b {{ display: block; font-size: 19px; color: {SILK}; letter-spacing: 0; text-transform: none;
  font-weight: 600; font-variant-numeric: tabular-nums; }}
.kd-counts .ok b {{ color: {JADE}; }}
.kd-working {{ font-size: 14px; color: {TUR}; }}
.kd-stop {{ font: inherit; font-size: 13px; font-weight: 600; color: {SILK}; background: transparent; cursor: pointer;
  border: 1px solid {SILK_2}; border-radius: 6px; padding: 4px 14px; min-height: 32px; margin-left: -12px; }}
.kd-stop:hover {{ border-color: {TUR}; color: {TUR}; }}
.kd-stop:focus-visible {{ outline: 2px solid {TUR}; outline-offset: 2px; }}
.kd-stop:disabled {{ opacity: .6; cursor: default; }}
#kd-stop-btn {{ display: none !important; }}
/* the shuttle: a turmeric thread crossing the header while a job runs */
.kd-shuttle {{ position: absolute; left: 232px; right: 0; bottom: -1px; height: 2px; overflow: hidden; }}
.kd-shuttle i {{ position: absolute; top: 0; height: 2px; width: 22%; background: {TUR};
  animation: kd-shuttle 2.4s cubic-bezier(.16,1,.3,1) infinite alternate; }}
@keyframes kd-shuttle {{ from {{ left: 0; }} to {{ left: 78%; }} }}
@media (prefers-reduced-motion: reduce) {{ .kd-shuttle i {{ animation: none; width: 100%; opacity: .6; }} }}

/* ---- update strip */
#kd-update {{ background: {RAISED}; border-bottom: 1px solid {RULE}; padding: 8px 32px !important; gap: 12px !important;
  align-items: center; margin: 0 !important; flex-wrap: nowrap; }}
#kd-update .kd-update-msg {{ flex: 1 1 auto; }}
#kd-update .kd-update-msg p {{ font-size: 14px !important; margin: 0 !important; color: {SILK} !important; }}
#kd-update button {{ min-height: 40px; }}
.kd-version {{ align-items: center; margin-bottom: 8px !important; }}

/* ---- body: step rail + work area */
#kd-body {{ gap: 0 !important; align-items: stretch; flex-wrap: nowrap; }}
#kd-rail {{ background: {RAIL}; border-right: 1px solid {RULE}; padding: 16px 0 24px !important; gap: 0 !important;
  flex: 0 0 232px !important; min-width: 232px !important; min-height: calc(100vh - 81px); }}
#kd-rail > * {{ margin: 0 !important; }}
#kd-rail button.kd-step {{ justify-content: flex-start; text-align: left; gap: 14px; width: 100%;
  background: transparent; border: 0; border-left: 3px solid transparent; border-radius: 0; box-shadow: none;
  color: {SILK_2}; font-size: 15px; font-weight: 500; padding: 12px 21px; min-height: 48px; }}
#kd-rail button.kd-step:hover {{ background: {RAISED}; color: {SILK}; }}
#kd-rail button.kd-step::before {{ content: ""; flex: 0 0 24px; height: 24px; display: grid; place-items: center;
  border: 1px solid {RULE_L}; font-size: 12px; font-weight: 600; color: {SILK_2}; font-variant-numeric: tabular-nums; }}
#rail-upload::before {{ content: "1" !important; }} #rail-settings::before {{ content: "2" !important; }}
#rail-review::before {{ content: "3" !important; }} #rail-blur::before {{ content: "4" !important; }}
#rail-export::before {{ content: "5" !important; }}
#kd-rail button.kd-extra::before {{ display: none; }}
#kd-rail button.kd-step::after {{ margin-left: auto; font-size: 12px; font-weight: 400; color: {SILK_3};
  font-family: 'KD Kantumruy', 'KD Noto Khmer', sans-serif; }}
#kd-rail button.kd-step.on::after, #kd-rail button.kd-step:hover::after {{ color: {SILK_2}; }}
#rail-upload::after {{ content: "ផ្ទុកឡើង"; }}
#rail-settings::after {{ content: "ការកំណត់"; }}
#rail-review::after {{ content: "ពិនិត្យ"; }}
#rail-blur::after {{ content: "បិទអក្សរ"; }}
#rail-export::after {{ content: "នាំចេញ"; }}
#rail-cut::after {{ content: "កាត់"; }}
#rail-batch::after {{ content: "ច្រើនភាគ"; }}
#rail-help::after {{ content: "ជំនួយ"; }}
#kd-rail button.kd-extra {{ padding-left: 59px; }}
#rail-cut {{ margin-top: 24px !important; border-top: 1px solid {RULE} !important; padding-top: 16px; }}
#kd-rail button.kd-step.done::before {{ background: {JADE}; border-color: {JADE}; color: {GROUND}; }}
#kd-rail button.kd-step.on {{ background: {RAISED}; color: {SILK}; border-left-color: {TUR}; }}
#kd-rail button.kd-step.on::before {{ border-color: {TUR}; color: {TUR}; }}
#kd-rail button.kd-step.on.done::before {{ background: {TUR}; color: {TUR_INK}; }}
#kd-main {{ padding: 32px 32px 56px !important; min-width: 0; gap: 0 !important; }}
#kd-tabs > .tab-wrapper {{ display: none !important; }}
#kd-tabs, #kd-tabs .tabitem {{ border: 0 !important; padding: 0 !important; background: transparent !important; }}

/* ---- type */
.kd-title h2 {{ font-size: 22px !important; font-weight: 600 !important; margin: 0 0 4px !important; color: {SILK}; }}
.kd-title h2 .kd-km {{ font-size: 15px; font-weight: 400; color: {SILK_2}; margin-left: 12px; }}
.kd-title p, .kd-hint, .kd-hint p {{ font-size: 14px !important; color: {SILK_2} !important; margin: 0 !important; }}
.kd-title {{ margin-bottom: 8px !important; }}
.kd-title .prose > *:last-child, .kd-title p:last-child {{ margin-bottom: 0 !important; }}
.kd-group {{ font-size: 12px !important; letter-spacing: .06em; text-transform: uppercase; color: {SILK_2} !important;
  border-bottom: 1px solid {RULE}; padding: 0 0 8px !important; margin: 8px 0 4px !important; }}
.kd-group p {{ margin: 0 !important; }}
.kd-group .kd-group, .kd-group .prose {{ border: 0 !important; padding: 0 !important; margin: 0 !important; }}
#kd-refresh {{ align-self: stretch; height: auto; min-height: 100%; }}
.kd-msg p {{ font-size: 15px !important; margin: 8px 0 0 !important; }}
.kd-actions {{ margin-top: 24px !important; gap: 12px !important; }}
.kd-actions button {{ min-height: 52px; font-size: 16px !important; font-weight: 600 !important; }}
label span, .block-title {{ letter-spacing: .01em; }}

/* ---- facts list (upload) */
.kd-facts {{ display: grid; grid-template-columns: 140px 1fr; border-top: 1px solid {RULE}; font-size: 15px; }}
.kd-facts dt, .kd-facts dd {{ padding: 10px 0; border-bottom: 1px solid {RULE}; margin: 0; }}
.kd-facts dt {{ color: {SILK_2}; font-size: 13px; }}
.kd-facts dd {{ font-variant-numeric: tabular-nums; }}
.kd-facts .est {{ color: {TUR}; font-weight: 600; }}

/* ---- weft band (review) */
.kd-weft {{ margin: 0 0 24px; }}
.kd-weft-head {{ display: flex; justify-content: space-between; font-size: 13px; color: {SILK_2}; margin-bottom: 8px; gap: 16px; }}
.kd-weft-key {{ display: flex; gap: 16px; }}
.kd-weft-key span::before {{ content: ""; display: inline-block; width: 10px; height: 10px; margin-right: 6px;
  vertical-align: -1px; background: var(--c); }}
.kd-weft-key span.k-un::before {{ background: linear-gradient(90deg, {LAC} 50%, {SKY} 50%); opacity: .42; }}
.kd-weft-key span.k-raw::before {{ background: repeating-linear-gradient(90deg, {RULE_L} 0 1px, transparent 1px 3px);
  outline: 1px solid {RULE}; }}
.kd-band {{ display: flex; height: 48px; background: {GROUND}; border: 1px solid {RULE}; }}
.kd-band i {{ height: 100%; min-width: 1px; display: block;
  background-image: repeating-linear-gradient(0deg, rgba(10,12,40,.22) 0 1px, transparent 1px 3px); }}
.kd-band i.g {{ background: transparent; }}
.kd-band i.sreymom {{ background-color: {LAC}; }} .kd-band i.piseth {{ background-color: {SKY}; }}
.kd-band i.un {{ opacity: .42; }}
.kd-band i.raw {{ background: repeating-linear-gradient(90deg, {RULE_L} 0 1px, transparent 1px 3px); }}
.kd-band i.cur {{ background-color: {TUR} !important; opacity: 1; box-shadow: 0 0 0 1px {SILK}; position: relative; z-index: 1; }}

/* ---- sync check */
.kd-marks {{ display: flex; height: 4px; margin-top: 2px; }}
.kd-marks i {{ display: block; height: 100%; min-width: 1px; }}
.kd-marks i.bad {{ background: {LAC_T}; }}
.kd-weft-key span.k-bad::before {{ height: 4px; vertical-align: 2px; background: {LAC_T}; }}
.kd-sync {{ align-items: center; gap: 16px !important; margin: -8px 0 16px !important; }}
.kd-syncline {{ font-size: 14px; color: {SILK_2}; }}
.kd-syncline b {{ color: {SILK}; font-weight: 600; }}
.kd-syncline .ok {{ color: {JADE}; font-weight: 600; }}
.kd-syncline .bad {{ color: {LAC_T}; font-weight: 600; }}
.kd-syncline .dim {{ color: {SILK_3}; }}
.kd-timing {{ align-items: stretch; gap: 8px !important; }}
.kd-timing > * {{ min-height: 40px; }}

/* ---- line editor */
.kd-voice label:nth-child(1):has(input:checked) {{ background: {LAC} !important; border-color: {LAC} !important;
  color: #ffffff !important; }}
.kd-voice label:nth-child(2):has(input:checked) {{ background: {SKY} !important; border-color: {SKY} !important;
  color: {GROUND} !important; }}
.kd-voice label:has(input:checked) span {{ color: inherit !important; font-weight: 600; }}
.kd-voice input:checked {{ background-color: {SILK} !important; border-color: {SILK} !important; }}
.kd-linehead p {{ font-size: 13px !important; color: {SILK_2} !important; margin: 0 !important;
  font-variant-numeric: tabular-nums; }}
.kd-zh textarea {{ color: {SILK_2} !important; font-size: 16px !important; }}
.kd-specimen textarea {{ font-size: 34px !important; line-height: 1.75 !important; font-weight: 500 !important;
  color: {SILK} !important; }}
@media (max-height: 960px) {{ .kd-specimen textarea {{ font-size: 30px !important; }} }}
.kd-next {{ border-top: 1px dashed {RULE_L}; padding-top: 12px; margin-top: 4px; font-size: 13px; color: {SILK_2}; }}
.kd-next b {{ display: block; font-size: 17px; font-weight: 500; color: {SILK_2}; line-height: 1.7; margin-top: 2px; }}

/* ---- tables */
.kd-table table {{ font-size: 15px; font-variant-numeric: tabular-nums; }}
.kd-table, .kd-table *:not(svg):not(path) {{ font-family: var(--font) !important; }}
.kd-table .body-cell {{ font-size: 15px; }}
.kd-table th {{ font-size: 12px !important; letter-spacing: .05em; text-transform: uppercase; color: {SILK_2} !important; }}
.kd-table td {{ line-height: 1.6; }}

/* ---- small screens: rail becomes a top strip */
@media (max-width: 900px) {{
  .kd-head {{ grid-template-columns: auto 1fr; }}
  .kd-mark {{ padding: 12px 16px; }}
  .kd-proj {{ padding: 12px 16px; gap: 12px; }}
  .kd-counts div {{ padding: 0 12px; }}
  #kd-rail button.kd-step::after {{ display: none; }}
  .kd-shuttle {{ left: 0; }}
  #kd-body {{ flex-direction: column !important; }}
  #kd-rail {{ flex: none !important; min-height: 0; min-width: 0 !important; width: 100%; flex-direction: row !important;
    overflow-x: auto; padding: 0 !important; border-right: 0; border-bottom: 1px solid {RULE}; }}
  #kd-rail button.kd-step {{ width: auto; border-left: 0; border-bottom: 3px solid transparent; padding: 10px 14px;
    white-space: nowrap; flex: 0 0 auto; gap: 8px; }}
  #kd-rail button.kd-step.on {{ border-bottom-color: {TUR}; }}
  #kd-rail button.kd-extra {{ padding-left: 14px; }}
  #rail-cut {{ margin-top: 0 !important; border-top: 0 !important; padding-top: 10px; border-left: 1px solid {RULE} !important; }}
  #kd-main {{ padding: 20px 16px 40px !important; }}
  .kd-specimen textarea {{ font-size: 24px !important; }}
  .kd-weft-head {{ flex-direction: column; gap: 6px; }}
  #kd-editor {{ order: -1; }}
  .kd-table .virtual-table-viewport {{ max-height: 360px !important; }}
  .kd-weft-key {{ flex-wrap: wrap; gap: 4px 12px; }}
}}
@media (max-width: 600px) {{
  .kd-head {{ grid-template-columns: 1fr; }}
  .kd-mark {{ border-right: 0; border-bottom: 1px solid {RULE}; flex-direction: row; align-items: baseline; gap: 12px; }}
  .kd-counts {{ margin-left: 0; width: 100%; }}
  .kd-counts div:first-child {{ border-left: 0; padding-left: 0; }}
  .kd-table {{ overflow-x: auto !important; }}
  .kd-table .table-container, .kd-table .table-wrap {{ min-width: 640px; }}
}}
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
        raise gr.Error("Upload a video first, or pick a saved project.")
    d = Path(d)
    vids = list(d.glob("source.*"))
    if not vids:
        raise gr.Error(f"No video found in {d}")
    return Project(vids[0], d)


def _proj_or_none(d) -> Project | None:
    try:
        return project_from_dir(d) if d else None
    except Exception:
        return None


def fmt_t(t: float, decimals: bool = True) -> str:
    m, s = divmod(max(0.0, t), 60)
    h, m = divmod(m, 60)
    sec = f"{s:04.1f}" if decimals else f"{int(s):02d}"
    return f"{int(h)}:{int(m):02d}:{sec}" if h else f"{int(m)}:{sec}"


def _duration(proj: Project) -> float:
    from .media import video_info

    return video_info(proj.video).duration


# =========================================================== rendered pieces ==
def table_value(proj: Project | None, cur: int | None = None, only_fix: bool = False):
    """Line table as a styled DataFrame: the current line raised with a turmeric number, checked line numbers
    in jade, voices in their dye colour, Khmer larger than the muted Chinese."""
    import pandas as pd

    cols = ["#", "Time", "Chinese", "Khmer", "Voice", "Fit"]
    if proj is None or not proj.has_segments():
        return pd.DataFrame([], columns=cols)
    segs = proj.load_segments()
    fits = _report(proj)["lines"]
    rows = [[i + 1, fmt_t(s.start, False), s.zh, s.km, "Sreymom" if s.voice == "sreymom" else "Piseth",
             fit_text(fits.get(s.id))] for i, s in enumerate(segs)]
    keep = [i for i, s in enumerate(segs) if not only_fix or fits.get(s.id, {}).get("status") in TO_FIX or i == cur]
    df = pd.DataFrame([rows[i] for i in keep], columns=cols, index=keep)
    checked = [s.checked for s in segs]
    status = [fits.get(s.id, {}).get("status", "none") for s in segs]

    def row_style(row):
        i = row.name
        out = [""] * len(cols)
        if checked[i]:
            out[0] = f"color: {JADE}; font-weight: 600"
        out[2] = f"color: {SILK_2}"
        out[3] = "font-size: 17px; line-height: 1.7" + ("" if row["Khmer"] else f"; background-color: {RAISED}")
        out[4] = f"color: {LAC_T if row['Voice'] == 'Sreymom' else SKY_T}"
        st = status[i]
        out[5] = (f"color: {JADE}" if st == "ok" else f"color: {LAC_T}; font-weight: 600" if st in PROBLEM
                  else f"color: {SILK_3}" if st in ("changed", "none") else f"color: {SILK_2}")
        if i == cur:
            out = [o + f"; background-color: {RAISED}" for o in out]
            out[0] = f"background-color: {TUR}; color: {TUR_INK}; font-weight: 600"
        return out

    return df.style.apply(row_style, axis=1)


def header_html(proj: Project | None, working: str = "") -> str:
    mark = '<div class="kd-mark"><b>Khmer Dub</b><span>ឌប់ខ្មែរ</span></div>'
    work = ""
    if working:  # a job is running: show its step, and Stop (until it is stopping)
        stop = ("" if working.startswith("Stopping") else
                '<button type="button" class="kd-stop" title="Stop this job. Finished steps are kept.">Stop</button>')
        work = f'<span class="kd-working">{html.escape(working)}</span>{stop}'
    if proj is None:
        body = (f'<div class="kd-proj">{work}</div>' if work else
                '<div class="kd-proj"><span class="empty">No video open. Start with Upload.</span></div>')
    else:
        segs = proj.load_segments() if proj.has_segments() else []
        n, n_km, n_ck = len(segs), sum(1 for s in segs if s.km.strip()), sum(1 for s in segs if s.checked)
        try:
            from .media import video_info

            info = video_info(proj.video)
            meta = f"{fmt_t(info.duration, False)} · {info.width}×{info.height}"
        except Exception:
            meta = ""
        video = "ready" if proj.output_video.exists() else "not yet"
        body = (f'<div class="kd-proj"><h1>{html.escape(proj.dir.name)}</h1><span class="meta">{meta}</span>{work}'
                f'<div class="kd-counts"><div>Lines<b>{n}</b></div>'
                f'<div class="{"ok" if n and n_km == n else ""}">In Khmer<b>{n_km}</b></div>'
                f'<div class="{"ok" if n and n_ck == n else ""}">Checked<b>{n_ck}</b></div>'
                f'<div class="{"ok" if video == "ready" else ""}">Video<b>{video}</b></div></div></div>')
    shuttle = '<div class="kd-shuttle"><i></i></div>' if working else ""
    return f'<div class="kd-head">{mark}{body}{shuttle}</div>'


def weft_html(proj: Project | None, cur: int | None = None, rep: dict | None = None) -> str:
    if proj is None or not proj.has_segments():
        return ('<div class="kd-weft"><div class="kd-weft-head"><span>The episode appears here after Settings → '
                'Start.</span></div><div class="kd-band"></div></div>')
    segs = proj.load_segments()
    try:
        total = max(_duration(proj), segs[-1].end)
    except Exception:
        total = segs[-1].end
    fits = (rep or _report(proj))["lines"]
    parts, marks, t = [], [], 0.0
    for i, s in enumerate(segs):
        if s.start > t + 0.05:
            parts.append(f'<i class="g" style="flex:{s.start - t:.2f}"></i>')
            marks.append(f'<i style="flex:{s.start - t:.2f}"></i>')
        bad = fits.get(s.id, {}).get("status") in PROBLEM
        marks.append(f'<i class="{"bad" if bad else ""}" style="flex:{max(s.duration, 0.15):.2f}"></i>')
        cls = "raw" if not s.km.strip() else s.voice + ("" if s.checked else " un")
        if i == cur:
            cls += " cur"
        tip = html.escape(f"{i + 1} · {fmt_t(s.start, False)} · {s.km[:60]}")
        parts.append(f'<i class="{cls}" style="flex:{max(s.duration, 0.15):.2f}" title="{tip}"></i>')
        t = max(t, s.end)
    if total > t:
        parts.append(f'<i class="g" style="flex:{total - t:.2f}"></i>')
        marks.append(f'<i style="flex:{total - t:.2f}"></i>')
    n_ck = sum(1 for s in segs if s.checked)
    key = (f'<span style="--c:{LAC}">Sreymom</span><span style="--c:{SKY}">Piseth</span>'
           f'<span style="--c:{TUR}">this line</span><span class="k-un">faded = not checked</span>'
           f'<span class="k-bad">runs over</span>')
    if any(not s.km.strip() for s in segs):
        key += '<span class="k-raw">striped = no Khmer yet</span>'
    return (f'<div class="kd-weft"><div class="kd-weft-head"><span>Episode · {len(segs)} lines · {n_ck} checked · '
            f'block width = line length</span><span class="kd-weft-key">{key}</span></div>'
            f'<div class="kd-band">{"".join(parts)}</div><div class="kd-marks">{"".join(marks)}</div></div>')


def facts_html(proj: Project) -> str:
    from .devices import has_nvidia_gpu
    from .media import video_info
    from .pipeline import estimate_minutes

    info = video_info(proj.video)
    s = proj.load_settings()
    gpu = has_nvidia_gpu()
    lo, hi = estimate_minutes(info.duration, gpu, s.remove_voice, s.blur != "off", s.blur_sample_fps)
    size_mb = proj.video.stat().st_size / 1e6
    return (f'<dl class="kd-facts"><dt>Length</dt><dd>{fmt_t(info.duration, False)}</dd>'
            f"<dt>Picture</dt><dd>{info.width}×{info.height} · {size_mb:,.0f} MB</dd>"
            f"<dt>This computer</dt><dd>{'NVIDIA graphics card' if gpu else 'No graphics card (slower)'}</dd>"
            f'<dt>Time needed</dt><dd class="est">about {lo}–{hi} min</dd></dl>')


def next_html(proj: Project, idx: int) -> str:
    segs = proj.load_segments() if proj.has_segments() else []
    if idx + 1 < len(segs):
        nxt = segs[idx + 1]
        return (f'<div class="kd-next">Next · line {idx + 2}<b>{html.escape(nxt.km or nxt.zh)}</b></div>')
    return '<div class="kd-next">Last line</div>'


def frame_at(proj: Project, t: float, width: int = 960):
    """The picture at `t`, `width` pixels wide (decoded by ffmpeg, which reads AV1 and every other format)."""
    from .media import frame_at as grab
    from .media import video_info

    frame = grab(proj.video, t, width)
    if frame is None:
        return None, 1.0
    return frame, width / video_info(proj.video).width


# =========================================================== background runs ==
def run_in_background(work, progress: gr.Progress):
    """Run `work(log, prog)` in a thread; yield (log_text, message, done, result, error) every second."""
    lines: list[str] = []
    state = {"f": 0.0, "m": "Starting"}
    out: dict = {}

    def log(msg: str) -> None:
        lines.append(msg)

    def prog(f: float, m: str) -> None:
        jobs.check()  # Stop was pressed: end here, at a safe point
        state["f"], state["m"] = f, m

    def target():
        try:
            out["result"] = work(log, prog)
        except jobs.Stopped as e:
            out["error"] = e
            lines.append(STOPPED)
        except Exception as e:  # shown in the app
            out["error"] = e
            lines.append("ERROR: " + str(e))
            lines.append(traceback.format_exc(limit=4))
        finally:
            jobs.end()

    jobs.begin()
    th = threading.Thread(target=target, daemon=True)
    th.start()
    while th.is_alive():
        msg = "Stopping… (at the next safe point)" if jobs.requested() else f"{state['m']} · {state['f'] * 100:.0f}%"
        progress(state["f"], desc=state["m"])
        yield "\n".join(lines[-300:]), msg, False, None, None
        time.sleep(1.0)
    yield "\n".join(lines[-300:]), state["m"], True, out.get("result"), out.get("error")


STOPPED = "Stopped. Finished steps are kept: press the same button again to continue."


def _warn(pipes) -> None:
    """Show what a finished job wants the user to know (e.g. lines the voice service skipped)."""
    for pl in pipes:
        for w in pl.warnings:
            gr.Warning(w)


def _stopped(err) -> bool:
    """The job was stopped on purpose: say so quietly (no red error)."""
    if isinstance(err, jobs.Stopped):
        gr.Info(STOPPED)
        return True
    return False


def _friendly(err: BaseException) -> str:
    if isinstance(err, jobs.Stopped):
        return STOPPED
    msg = str(err)
    if "Could not extract audio" in msg:
        return "This video has no sound track, or the file is damaged."
    if msg.startswith("The Khmer voice service"):
        return msg
    if "429" in msg and "translate" in msg.lower():
        from .translate import GOOGLE_BUSY

        return GOOGLE_BUSY
    if "edge" in msg.lower() or "WSServerHandshake" in msg or "ClientConnector" in msg:
        return ("Could not reach the Khmer voice service (it needs internet). Check the connection and press "
                "the button again; it continues where it stopped.")
    return msg[:600]


def _bound(bound, proj_dir_value: str, idx) -> bool:
    """Is the editor showing exactly this project's line?"""
    try:
        return bool(bound) and bound == f"{proj_dir_value}|{int(idx)}"
    except (TypeError, ValueError):
        return False


def _box_rows(box_list) -> list[list]:
    return [[round(b["x"] * 100, 1), round(b["y"] * 100, 1), round(b["w"] * 100, 1), round(b["h"] * 100, 1),
             b.get("start", "start"), b.get("end", "end")] for b in box_list or []]


def _save_boxes(proj: Project, box_list) -> None:
    s = proj.load_settings()
    s.blur_regions = list(box_list)
    proj.save_settings(s)


def _bgr(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)


# =========================================================== the app ==========
def build_app() -> gr.Blocks:  # noqa: C901 - one layout function is the easiest way to read UI code
    from .pipeline import Pipeline

    with gr.Blocks(title="Khmer Dub") as app:
        proj_dir = gr.State(None)
        boxes = gr.State([])  # manual blur boxes (fractions of the frame)
        pending_pt = gr.State(None)  # first click of a new blur box
        line_idx = gr.State(0)  # line shown in the editor
        editor_for = gr.State(None)  # "<project folder>|<line>" the editor is showing; edits go only there

        head = gr.HTML(header_html(None), elem_id="kd-head")
        stop_trigger = gr.Button("Stop", elem_id="kd-stop-btn")  # clicked by the header's Stop (STOP_JS)

        def do_stop() -> None:
            jobs.request()  # the running job ends at its next safe point; nothing happens if none is running

        stop_trigger.click(do_stop, None, None, queue=False, show_progress="hidden")

        # update strip: shown only when a newer release exists (or one was just installed)
        with gr.Row(visible=False, elem_id="kd-update", equal_height=True) as upd_row:
            upd_msg = gr.Markdown("", elem_classes="kd-update-msg")
            upd_btn = gr.Button("Update now", variant="primary", scale=0, min_width=140)
            upd_later = gr.Button("Later", scale=0, min_width=96)

        with gr.Row(elem_id="kd-body", equal_height=False):
            with gr.Column(elem_id="kd-rail", scale=0, min_width=232):
                rail = {sid: gr.Button(label, elem_id=f"rail-{sid}", elem_classes=["kd-step"] + (["on"] if i == 0 else []))
                        for i, (sid, label) in enumerate(STEPS)}
                rail.update({sid: gr.Button(label, elem_id=f"rail-{sid}", elem_classes=["kd-step", "kd-extra"])
                             for sid, label in EXTRAS})
            rail_list = list(rail.values())

            with gr.Column(elem_id="kd-main", scale=1):
                with gr.Tabs(elem_id="kd-tabs") as tabs:
                    # ---------------------------------------------- upload
                    with gr.Tab("Upload", id="upload"):
                        gr.Markdown("## Upload <span class='kd-km'>ផ្ទុកឡើង</span>\nA Chinese video in any common format. One-hour episodes are fine.",
                                    elem_classes="kd-title")
                        with gr.Row(equal_height=False):
                            with gr.Column(scale=3):
                                upload = gr.File(label="Chinese video", file_types=["video"], type="filepath",
                                                 height=200)
                                with gr.Row(equal_height=True):
                                    existing = gr.Dropdown(label="Or continue a saved project", choices=list_projects(),
                                                           value=None, scale=5)
                                    refresh = gr.Button("Refresh list", scale=1, min_width=120, elem_id="kd-refresh")
                            with gr.Column(scale=2):
                                thumb = gr.Image(interactive=False, height=220, show_label=False)
                                facts = gr.HTML("", elem_classes="kd-html")
                        with gr.Row(elem_classes="kd-actions"):
                            to_settings = gr.Button("Continue to settings", variant="primary")
                            auto_all_1 = gr.Button("Do everything automatically")

                    # ---------------------------------------------- settings
                    with gr.Tab("Settings", id="settings"):
                        gr.Markdown("## Settings <span class='kd-km'>ការកំណត់</span>\nPick a starting point. Everything below can be changed.",
                                    elem_classes="kd-title")
                        preset = gr.Radio(choices=PRESET_CHOICES, value="free", show_label=False)
                        with gr.Row(equal_height=False):
                            with gr.Column():
                                gr.Markdown("Translation", elem_classes="kd-group")
                                translator = gr.Dropdown(label="Translator", choices=[(v, k) for k, v in ENGINES.items()],
                                                         value="google")
                                translator_help = gr.Markdown(TRANSLATOR_HELP["google"], elem_classes="kd-hint")
                                provider = gr.Dropdown(label="AI service",
                                                       choices=[("OpenRouter · free models", "openrouter"),
                                                                ("Groq · free, fast", "groq"),
                                                                ("DeepSeek · cheap, strong at Chinese", "deepseek"),
                                                                ("Ollama · on this computer", "ollama"),
                                                                ("Other · paste address", "other")],
                                                       value="openrouter", visible=False)
                                base_url = gr.Textbox(label="API address (base URL)", visible=False,
                                                      placeholder="https://…/v1")
                                api_key = gr.Textbox(label="API key", type="password", visible=False,
                                                     placeholder="Paste your key (kept only while the app is open)")
                                model = gr.Textbox(label="Model (optional)", visible=False, placeholder="default")
                                gr.Markdown("Khmer voice", elem_classes="kd-group")
                                voice_mode = gr.Radio(label="Who speaks",
                                                      choices=[("Automatic · woman Sreymom, man Piseth", "auto"),
                                                               ("Only Sreymom", "sreymom"), ("Only Piseth", "piseth")],
                                                      value="auto")
                                with gr.Row():
                                    voice_speed = gr.Slider(-30, 30, value=0, step=5, label="Speed (%)")
                                    voice_pitch = gr.Slider(-20, 20, value=0, step=2, label="Pitch (Hz)")
                                remove_voice = gr.Checkbox(label="Remove the Chinese voice, keep music and effects",
                                                           value=True)
                            with gr.Column():
                                gr.Markdown("Khmer subtitles", elem_classes="kd-group")
                                subtitles = gr.Radio(label="Subtitles",
                                                     choices=[("In the picture", "burn"),
                                                              ("Separate track", "soft"), ("None", "none")],
                                                     value="burn")
                                with gr.Row():
                                    subtitle_position = gr.Radio(label="Position", choices=[("Bottom", "bottom"),
                                                                                           ("Top", "top")],
                                                                 value="bottom")
                                    subtitle_color = gr.Radio(label="Colour", choices=[("White", "white"),
                                                                                      ("Yellow", "yellow")],
                                                              value="white")
                                with gr.Row():
                                    subtitle_size = gr.Slider(0.6, 1.8, value=1.0, step=0.05, label="Size")
                                    subtitle_box = gr.Checkbox(label="Dark box behind text", value=False)
                                gr.Markdown("Blur Chinese text", elem_classes="kd-group")
                                blur = gr.Radio(label="Automatic blur",
                                                choices=[("Chinese text", "chinese"), ("All text", "all"),
                                                         ("Off", "off")], value="chinese")
                                with gr.Row():
                                    blur_style = gr.Radio(label="Look", choices=[("Blur", "blur"),
                                                                                ("Pixels", "pixelate"),
                                                                                ("Dark box", "box")], value="blur")
                                    blur_sample_fps = gr.Radio(label="Scan", choices=[("Fast", 2.0), ("Normal", 3.0),
                                                                                     ("Careful", 5.0)], value=3.0)
                        with gr.Accordion("More options", open=False):
                            with gr.Row():
                                whisper_model = gr.Dropdown(label="Speech recognition",
                                                            choices=[("Auto · best for this computer", "auto"),
                                                                     ("small · fastest", "small"), ("medium", "medium"),
                                                                     ("large-v3-turbo · with a GPU", "large-v3-turbo"),
                                                                     ("large-v3 · most accurate", "large-v3")],
                                                            value="auto")
                                video_quality = gr.Radio(label="Video quality",
                                                         choices=[("Fast", "fast"), ("Balanced", "balanced"),
                                                                  ("High", "high")], value="balanced")
                                resolution = gr.Dropdown(label="Output size",
                                                         choices=[("Same as original", "original"), ("1080p", "1080"),
                                                                  ("720p", "720"), ("480p", "480")], value="original")
                            with gr.Row():
                                max_speedup = gr.Slider(1.0, 2.0, value=1.5, step=0.05, label="Max voice speed-up",
                                                        info="Khmer is often longer than Chinese")
                                background_volume = gr.Slider(0, 2, value=1.0, step=0.05, label="Music volume")
                                dub_volume = gr.Slider(0.2, 2, value=1.0, step=0.05, label="Khmer voice volume")
                            keep_original_audio = gr.Checkbox(label="Keep the Chinese sound as a second audio track",
                                                              value=False)
                            fit_mode = gr.Radio(label="Voice timing",
                                                choices=[("Match the character: start and end with them", "match"),
                                                         ("Natural speed: only speed up when a line runs over",
                                                          "natural")], value="match")
                            with gr.Row():
                                zh_srt = gr.File(label="Chinese .srt (skips speech recognition)", file_types=[".srt"],
                                                 type="filepath", height=90)
                                km_srt = gr.File(label="Khmer .srt (skips transcript and translation)",
                                                 file_types=[".srt"], type="filepath", height=90)
                        with gr.Row(elem_classes="kd-actions"):
                            start_prepare = gr.Button("Start · transcript and Khmer translation", variant="primary")
                            auto_all_2 = gr.Button("Do everything automatically")
                        prep_msg = gr.Markdown("", elem_classes="kd-msg")

                    # ---------------------------------------------- review
                    with gr.Tab("Review", id="review"):
                        gr.Markdown("## Review <span class='kd-km'>ពិនិត្យ</span>\nClick a line to check it. Listen, fix the Khmer, pick the voice, "
                                    "then Save and next.", elem_classes="kd-title")
                        weft = gr.HTML(weft_html(None), elem_classes="kd-html")
                        with gr.Row(equal_height=True, elem_classes="kd-sync"):
                            sync_info = gr.HTML(sync_html(None), elem_classes="kd-html")
                            only_fix = gr.Checkbox(label="Only lines to fix", value=False, scale=0, min_width=170)
                            make_voices_btn = gr.Button("Check timing", scale=0, min_width=150)
                        with gr.Row(equal_height=False):
                            with gr.Column(scale=3, min_width=560, elem_id="kd-lines"):
                                table = gr.Dataframe(value=table_value(None), type="array", interactive=False,
                                                     wrap=True, max_height=620, show_label=False,
                                                     column_widths=["6%", "8%", "22%", "36%", "14%", "14%"],
                                                     elem_classes="kd-table")
                            with gr.Column(scale=2, min_width=320, elem_id="kd-editor"):
                                line_title = gr.Markdown("Pick a line on the left.", elem_classes="kd-linehead")
                                zh_text = gr.Textbox(label="Chinese", interactive=False, lines=1, elem_classes="kd-zh")
                                km_text = gr.Textbox(label="Khmer", lines=2, max_lines=4, elem_classes="kd-specimen")
                                line_voice = gr.Radio(label="Voice", choices=[("Sreymom", "sreymom"),
                                                                             ("Piseth", "piseth")], value="sreymom",
                                                      elem_classes="kd-voice")
                                with gr.Row(equal_height=True, elem_classes="kd-timing"):
                                    nudge_early = gr.Button("Earlier 0.1 s", min_width=110)
                                    nudge_late = gr.Button("Later 0.1 s", min_width=110)
                                    line_speed = gr.Dropdown(choices=SPEED_CHOICES, value="auto", show_label=False,
                                                             container=False, min_width=130)
                                    shorten_btn = gr.Button("Shorten", min_width=90)
                                with gr.Row():
                                    play_zh = gr.Button("Play original", min_width=100)
                                    play_km = gr.Button("Play Khmer", min_width=100)
                                    play_vid = gr.Button("Play in video", min_width=110)
                                line_audio = gr.Audio(type="filepath", autoplay=True, interactive=False, visible=False,
                                                      show_label=False)
                                line_video = gr.Video(autoplay=True, interactive=False, visible=False, height=260,
                                                      show_label=False)
                                with gr.Row():
                                    prev_line = gr.Button("Previous", scale=1, min_width=80)
                                    save_line = gr.Button("Save", scale=1, min_width=80)
                                    next_line = gr.Button("Save and next", variant="primary", scale=2, min_width=150)
                                next_prev = gr.HTML("", elem_classes="kd-html")
                                with gr.Accordion("All lines", open=False):
                                    with gr.Row():
                                        find_txt = gr.Textbox(label="Find (Khmer)")
                                        repl_txt = gr.Textbox(label="Replace with")
                                    replace_btn = gr.Button("Replace in every line")
                                    with gr.Row():
                                        all_sreymom = gr.Button("All lines Sreymom")
                                        all_piseth = gr.Button("All lines Piseth")
                                    retranslate = gr.Button("Translate everything again")
                        with gr.Row(elem_classes="kd-actions"):
                            to_blur = gr.Button("Continue to blur", variant="primary")

                    # ---------------------------------------------- blur
                    with gr.Tab("Blur", id="blur"):
                        gr.Markdown("## Blur <span class='kd-km'>បិទអក្សរ</span>\nGreen boxes are found automatically. Click two corners of any text "
                                    "they miss to add your own box.", elem_classes="kd-title")
                        with gr.Row(equal_height=False):
                            with gr.Column(scale=3):
                                blur_t = gr.Slider(0, 60, value=5, step=0.5, label="Position in the video (seconds)")
                                blur_img = gr.Image(interactive=False, height=460, show_label=False)
                            with gr.Column(scale=2):
                                scan_btn = gr.Button("Scan the whole video now")
                                scan_msg = gr.Markdown("", elem_classes="kd-hint")
                                box_whole = gr.Checkbox(label="New boxes cover the whole video", value=True)
                                with gr.Row():
                                    box_from = gr.Number(label="Or only from (s)", value=None)
                                    box_to = gr.Number(label="to (s)", value=None)
                                box_table = gr.Dataframe(headers=["x %", "y %", "w %", "h %", "from", "to"],
                                                         type="array", interactive=False, label="Your boxes",
                                                         max_height=180, elem_classes="kd-table")
                                with gr.Row():
                                    undo_box = gr.Button("Remove last box")
                                    clear_box = gr.Button("Remove all")
                                preview_btn = gr.Button("Preview 20 seconds from here")
                                preview_vid = gr.Video(interactive=False, height=240, show_label=False)
                        with gr.Row(elem_classes="kd-actions"):
                            to_export = gr.Button("Continue to export", variant="primary")

                    # ---------------------------------------------- export
                    with gr.Tab("Export", id="export"):
                        gr.Markdown("## Export <span class='kd-km'>នាំចេញ</span>\nMakes the Khmer voice, mixes it with the music, blurs the text "
                                    "and writes the video.", elem_classes="kd-title")
                        make_btn = gr.Button("Make the Khmer video", variant="primary", elem_classes="kd-actions")
                        with gr.Row(equal_height=False):
                            with gr.Column(scale=3):
                                result = gr.Video(interactive=False, height=440, show_label=False)
                            with gr.Column(scale=2):
                                downloads = gr.File(label="Downloads", file_count="multiple", interactive=False)
                                gr.Markdown("Video (.mp4), Khmer subtitles (.srt), Khmer sound (.m4a) and the Chinese "
                                            "transcript. Split it for TikTok or Facebook in Cut.", elem_classes="kd-hint")
                                folder = gr.Textbox(label="Project folder", interactive=False)
                        with gr.Accordion("Log", open=False):
                            log_box = gr.Textbox(lines=12, max_lines=30, autoscroll=True, show_label=False)

                    # ---------------------------------------------- cut
                    with gr.Tab("Cut", id="cut"):
                        gr.Markdown("## Cut <span class='kd-km'>កាត់</span>\nSplit a video into parts, or keep only part of it. Takes seconds, "
                                    "even for a one-hour episode.", elem_classes="kd-title")
                        with gr.Row(equal_height=False):
                            with gr.Column():
                                cut_src = gr.Radio(label="Which video",
                                                   choices=[("The finished Khmer video", "khmer"),
                                                            ("The original Chinese video", "original")],
                                                   value="khmer")
                                cut_every = gr.Radio(label="Split into parts of",
                                                     choices=[("10 min", 10.0), ("15 min", 15.0), ("Other", -1.0),
                                                              ("Don't split", 0.0)], value=15.0)
                                cut_custom = gr.Number(label="Minutes per part", value=5, visible=False)
                                with gr.Row():
                                    cut_from = gr.Textbox(label="Keep from", placeholder="0:00 = start")
                                    cut_to = gr.Textbox(label="to", placeholder="empty = end")
                                cut_projects = gr.Checkbox(label="Open each part as its own project (to dub a long "
                                                                 "episode piece by piece)", value=False, visible=False)
                                cut_btn = gr.Button("Cut", variant="primary")
                            with gr.Column():
                                cut_out = gr.File(label="Parts", file_count="multiple", interactive=False)
                                cut_msg = gr.Markdown("", elem_classes="kd-msg")

                    # ---------------------------------------------- batch
                    with gr.Tab("Batch", id="batch"):
                        gr.Markdown("## Batch <span class='kd-km'>ច្រើនភាគ</span>\nAdd several episodes. Each is done automatically with the current "
                                    "settings, one after another. Good for a whole series overnight.",
                                    elem_classes="kd-title")
                        batch_files = gr.File(label="Videos", file_count="multiple", file_types=["video"],
                                              type="filepath")
                        batch_btn = gr.Button("Process all", variant="primary")
                        batch_table = gr.Dataframe(headers=["Video", "Status"], type="array", interactive=False,
                                                   elem_classes="kd-table")
                        batch_out = gr.File(label="Finished videos", file_count="multiple", interactive=False)

                    # ---------------------------------------------- help
                    with gr.Tab("Help", id="help"):
                        with gr.Row(equal_height=True, elem_classes="kd-version"):
                            gr.Markdown(f"Khmer Dub **{__version__}**", elem_classes="kd-hint")
                            chk_btn = gr.Button("Check for updates", scale=0, min_width=180)
                        chk_msg = gr.Markdown("", elem_classes="kd-msg")
                        gr.Markdown(HELP_MD)

        # =================================================== event handlers ====
        # long jobs (voice removal, voices, scans, rendering) run one at a time, never two on the same files
        HEAVY = {"concurrency_id": "heavy", "concurrency_limit": 1}

        comp = dict(zip(SETTING_FIELDS, [
            translator, provider, base_url, model, whisper_model, voice_mode, voice_speed, voice_pitch, remove_voice,
            max_speedup, fit_mode, background_volume, dub_volume, subtitles, subtitle_size, subtitle_position, subtitle_color,
            subtitle_box, blur, blur_style, blur_sample_fps, video_quality, resolution, keep_original_audio]))
        setting_comps = list(comp.values())

        def rail_state(active: str, proj: Project | None) -> dict:
            done = {}
            if proj is not None:
                segs = proj.load_segments() if proj.has_segments() else []
                done = {"upload": True, "settings": bool(segs),
                        "review": bool(segs) and all(s.checked for s in segs),
                        "blur": any(proj.dir.glob("blur_*.json")), "export": proj.output_video.exists()}
            out = {}
            for sid, btn in rail.items():
                cls = ["kd-step"] + (["kd-extra"] if sid in dict(EXTRAS) else [])
                cls += (["on"] if sid == active else []) + (["done"] if done.get(sid) else [])
                out[btn] = gr.Button(elem_classes=cls)
            return out

        def go(target: str, proj_v) -> dict:
            return {tabs: gr.Tabs(selected=target), **rail_state(target, _proj_or_none(proj_v))}

        for sid, btn in rail.items():
            btn.click(lambda p, sid=sid: go(sid, p), [proj_dir], [tabs, *rail_list], queue=False)

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
            note = f" {PROVIDERS[prov][3]}." if custom and prov in PROVIDERS else ""
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

            s = proj.load_settings()
            dur = _duration(proj)
            frame, _ = frame_at(proj, min(5.0, dur / 3))
            out = {
                proj_dir: str(proj.dir), head: header_html(proj), facts: facts_html(proj),
                thumb: cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) if frame is not None else None,
                table: table_value(proj), weft: weft_html(proj), sync_info: sync_html(proj), boxes: s.blur_regions,
                box_table: _box_rows(s.blur_regions),
                blur_t: gr.update(maximum=max(1.0, round(dur, 1)), value=min(5.0, dur / 3)),
                folder: str(proj.dir), existing: gr.update(choices=list_projects(), value=proj.dir.name),
                result: str(proj.output_video) if proj.output_video.exists() else None,
                downloads: [str(p) for p in Pipeline(proj, s, log=lambda m: None).downloads()] or None,
            }
            out.update({c: getattr(s, name) for name, c in comp.items()})
            out.update(_translator_visibility(s.translator, s.translator_provider))
            out.update(rail_state("upload", proj))
            out.update(blank_editor())
            return out

        def blank_editor() -> dict:
            return {line_idx: 0, editor_for: None, line_title: "Pick a line on the left.", zh_text: "", km_text: "",
                    line_speed: "auto", line_audio: gr.Audio(value=None, visible=False),
                    line_video: gr.Video(value=None, visible=False), next_prev: ""}

        editor_comps = [line_idx, editor_for, line_title, zh_text, km_text, line_speed, line_audio, line_video,
                        next_prev]

        PICK_FIRST = "Pick a line in the table first."

        def not_picked(nothing):
            """No line picked (or it belongs to another project): say so, change nothing, no red error marks."""
            gr.Warning(PICK_FIRST)
            return nothing
        load_out = list(dict.fromkeys([proj_dir, head, facts, thumb, table, weft, sync_info, boxes, box_table, blur_t, folder,
                                       existing, result, downloads, *setting_comps, *vis_out, *rail_list,
                                       *editor_comps]))

        # an empty dict is not "no change" in Gradio (it counts as one value), so return one untouched output
        upload.upload(lambda p: load_into_ui(project_from_upload(p)) if p else {head: gr.update()}, [upload],
                      load_out)
        existing.select(lambda n: load_into_ui(project_from_dir(PROJECTS / n)) if n else {head: gr.update()},
                        [existing], load_out)
        refresh.click(lambda: gr.update(choices=list_projects()), None, [existing])
        to_settings.click(lambda p: go("settings", p), [proj_dir], [tabs, *rail_list], queue=False)

        # ---- settings
        def on_preset(p):
            if p not in PRESETS:
                return {translator_help: gr.update()}
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
                yield {head: header_html(proj, msg), log_box: text, prep_msg: msg}
            if err:
                yield {head: header_html(proj), prep_msg: f"**{_friendly(err)}**", log_box: text}
                if not _stopped(err):  # the message is shown in full above; a red badge would sit on top of it
                    gr.Warning(_friendly(err))
                return
            out = {head: header_html(proj), table: table_value(proj), weft: weft_html(proj), log_box: text,
                   prep_msg: "Done. Check the lines in Review.", **go("review", str(proj.dir))}
            out.update(refresh_editor(d, proj))
            yield out

        def refresh_editor(d, proj: Project) -> dict:
            """After a bulk change, show the line being edited again with its new text (or blank the editor)."""
            if _bound(d.get(editor_for), str(proj.dir), d.get(line_idx)) and proj.has_segments():
                return show_line(str(proj.dir), int(d[line_idx]), bool(d.get(only_fix)))
            return blank_editor()

        prep_in = {proj_dir, api_key, zh_srt, km_srt, boxes, line_idx, editor_for, only_fix, *setting_comps}
        prep_out = list(dict.fromkeys([head, table, weft, log_box, prep_msg, tabs, *rail_list, *editor_comps,
                                       weft, next_prev, sync_info, line_voice]))

        def do_prepare(d, progress=gr.Progress()):
            yield from _prepare(d, progress)

        def do_retranslate(d, progress=gr.Progress()):
            yield from _prepare(d, progress, retrans=True)

        start_prepare.click(do_prepare, prep_in, prep_out, show_progress_on=[prep_msg], **HEAVY)
        retranslate.click(do_retranslate, prep_in, prep_out, show_progress_on=[table], **HEAVY)

        # ---- everything automatically
        def do_all(d, progress=gr.Progress()):
            proj = project_from_dir(d[proj_dir])
            s = settings_from(d, proj)
            key = d.get(api_key) or None
            zh, km = d.get(zh_srt), d.get(km_srt)

            pipes: list = []

            def work(log, prog):
                pipes.append(Pipeline(proj, s, key, log, prog))
                return pipes[-1].run_all(Path(zh) if zh else None, Path(km) if km else None)

            text, res, first = "", None, True
            for text, msg, _done, res, err in run_in_background(work, progress):
                out = {head: header_html(proj, msg), log_box: text}
                if first:
                    out.update(go("export", str(proj.dir)))
                    first = False
                yield out
            if err:
                yield {head: header_html(proj), log_box: text}
                if _stopped(err):
                    return
                raise gr.Error(_friendly(err))
            gr.Info("The Khmer video is ready.")
            _warn(pipes)
            yield {head: header_html(proj), log_box: text, table: table_value(proj), weft: weft_html(proj),
                   result: str(res), downloads: [str(p) for p in Pipeline(proj, s, log=lambda m: None).downloads()],
                   **rail_state("export", proj), **blank_editor()}

        auto_out = list(dict.fromkeys([head, log_box, tabs, table, weft, result, downloads, *rail_list, *editor_comps]))
        auto_all_1.click(do_all, prep_in, auto_out, show_progress_on=[result], **HEAVY)
        auto_all_2.click(do_all, prep_in, auto_out, show_progress_on=[result], **HEAVY)

        # ---- review: line editor
        def show_line(proj_v, idx, only: bool = False) -> dict:
            proj = project_from_dir(proj_v)
            segs = proj.load_segments() if proj.has_segments() else []
            if not segs:
                return {line_title: "No lines yet. Press Start in Settings first."}
            idx = max(0, min(int(idx), len(segs) - 1))
            sg = segs[idx]
            rep = _report(proj)
            info = rep["lines"].get(sg.id)
            fit = f" · {fit_text(info)}" if info and info.get("status") != "none" else ""
            mark = " · checked" if sg.checked else ""
            nudge = f" · moved {sg.offset:+.1f} s" if abs(sg.offset) >= 0.05 else ""
            return {line_idx: idx, editor_for: f"{proj.dir}|{idx}",
                    line_title: f"Line {idx + 1} of {len(segs)} · {fmt_t(sg.start)} → {fmt_t(sg.end)}{nudge}{fit}{mark}",
                    zh_text: sg.zh, km_text: sg.km, line_voice: sg.voice,
                    line_speed: "auto" if sg.rate is None else str(sg.rate),
                    line_audio: gr.Audio(value=None, visible=False), line_video: gr.Video(value=None, visible=False),
                    weft: weft_html(proj, idx, rep), next_prev: next_html(proj, idx),
                    table: table_value(proj, idx, only), sync_info: sync_html(proj, rep)}

        line_out = [line_idx, editor_for, line_title, zh_text, km_text, line_voice, line_speed, line_audio, line_video,
                    weft, next_prev, table, sync_info]

        def on_table_select(proj_v, only, evt: gr.SelectData):
            try:
                idx = int(evt.row_value[0]) - 1  # the "#" column, so it also works when the table is filtered
            except Exception:
                idx = evt.index[0]
            return show_line(proj_v, idx, only)

        table.select(on_table_select, [proj_dir, only_fix], line_out)

        # keep the current line visible in the (virtualised) table on long episodes
        # reads "Line N of M" from the editor title (State values never reach the browser)
        scroll_js = """() => {
          let tries = 0;
          const step = () => {
            const vp = document.querySelector('.kd-table .virtual-table-viewport');
            const m = (document.querySelector('.kd-linehead')?.textContent || '').match(/Line (\\d+) of (\\d+)/);
            if (!vp || !m) { if (++tries < 20) setTimeout(step, 150); return; }
            const i = +m[1] - 1, n = +m[2], want = m[1];
            const row = [...vp.querySelectorAll('.virtual-row')].find(
              r => r.querySelector('.body-cell')?.textContent.trim() === want);
            const b = vp.getBoundingClientRect();
            if (row) {
              const a = row.getBoundingClientRect();
              if (a.top < b.top + 48 || a.bottom > b.bottom) {
                vp.scrollTop += a.top - b.top - b.height / 3; vp.dispatchEvent(new Event('scroll'));
              }
              return;
            }
            // virtual rows: jump near the line so it gets drawn, then align on the next pass
            vp.scrollTop = i / n * vp.scrollHeight - vp.clientHeight / 3; vp.dispatchEvent(new Event('scroll'));
            if (++tries < 20) setTimeout(step, 150);
          };
          setTimeout(step, 100);
        }"""

        def _store(proj_v, idx, km, voice, checked: bool, bound=None) -> Project:
            proj = project_from_dir(proj_v)
            if not _bound(bound, str(proj.dir), idx):  # callers check first; this is the last guard
                raise gr.Error(PICK_FIRST)
            segs = proj.load_segments() if proj.has_segments() else []
            if segs:
                sg = segs[max(0, min(int(idx), len(segs) - 1))]
                sg.km, sg.voice = (km or "").strip(), voice
                sg.checked = sg.checked or checked
                proj.save_segments(segs)
                # remember that voices are now hand-picked, so they aren't re-guessed
                proj.path("voices_mode.txt").write_text(proj.load_settings().voice_mode)
            return proj

        def do_save(proj_v, idx, km, voice, only, bound):
            if not _bound(bound, str(project_from_dir(proj_v).dir), idx):
                return not_picked({line_title: gr.update()})
            proj = _store(proj_v, idx, km, voice, True, bound)
            gr.Info("Saved")
            out = show_line(proj_v, idx, only)
            out.update({head: header_html(proj), **rail_state("review", proj)})
            return out

        def do_step(proj_v, idx, km, voice, only, bound, delta, save):
            if not _bound(bound, str(project_from_dir(proj_v).dir), idx):
                return not_picked({line_title: gr.update()})
            proj = _store(proj_v, idx, km, voice, True, bound) if save else project_from_dir(proj_v)
            idx, nxt = int(idx), int(idx) + delta
            if only:  # jump to the next line that still needs a look
                fits = _report(proj)["lines"]
                segs = proj.load_segments()
                order = range(idx + 1, len(segs)) if delta > 0 else range(idx - 1, -1, -1)
                nxt = next((i for i in order if fits.get(segs[i].id, {}).get("status") in TO_FIX), nxt)
            out = show_line(proj_v, nxt, only)
            out.update({head: header_html(proj), **rail_state("review", proj)})
            return out

        edit_in = [proj_dir, line_idx, km_text, line_voice, only_fix, editor_for]
        edit_out = [*line_out, head, *rail_list]
        for ev in (save_line.click(do_save, edit_in, edit_out),
                   next_line.click(lambda *a: do_step(*a, 1, True), edit_in, edit_out),
                   prev_line.click(lambda *a: do_step(*a, -1, False), edit_in, edit_out)):
            ev.then(None, None, None, js=scroll_js)

        only_fix.change(lambda p, i, o: table_value(project_from_dir(p), int(i or 0), o) if p else gr.update(),
                        [proj_dir, line_idx, only_fix], [table])

        # ---- timing tools for one line
        def _edit_timing(proj_v, idx, km, voice, only, bound, delta=None, speed=None):
            if not _bound(bound, str(project_from_dir(proj_v).dir), idx):
                return not_picked({line_title: gr.update()})
            proj = _store(proj_v, idx, km, voice, False, bound)
            segs = proj.load_segments()
            sg = segs[int(idx)]
            if delta is not None:
                sg.offset = round(max(-2.0, min(2.0, sg.offset + delta)), 2)
            if speed is not None:
                sg.rate = None if speed == "auto" else int(speed)
            proj.save_segments(segs)
            return show_line(proj_v, idx, only)

        nudge_early.click(lambda *a: _edit_timing(*a, delta=-0.1), edit_in, line_out)
        nudge_late.click(lambda *a: _edit_timing(*a, delta=0.1), edit_in, line_out)
        line_speed.input(lambda p, i, k, v, o, b, sp: _edit_timing(p, i, k, v, o, b, speed=sp),
                         [*edit_in, line_speed], line_out)

        def do_shorten(d, progress=gr.Progress()):
            from .translate import shorten

            proj = project_from_dir(d[proj_dir])
            if not _bound(d.get(editor_for), str(proj.dir), d[line_idx]):
                return not_picked(gr.update())
            sg = proj.load_segments()[int(d[line_idx])]
            progress(0.3, desc="Asking the AI for a shorter line")
            try:
                new = shorten(sg.zh, d[km_text] or sg.km, max(sg.duration, 0.6), d[translator], d[model] or "",
                              d.get(api_key) or None, d[provider], d[base_url] or "")
            except Exception as e:
                raise gr.Error(_friendly(e)) from e
            gr.Info("Shorter line ready. Listen to it, then Save.")
            return new

        shorten_btn.click(do_shorten, {proj_dir, line_idx, editor_for, km_text, translator, model, api_key, provider,
                                       base_url},
                          [km_text], show_progress_on=[km_text])

        def do_play_zh(proj_v, idx, bound):
            proj = project_from_dir(proj_v)
            if not _bound(bound, str(proj.dir), idx):
                return not_picked(gr.update())
            segs = proj.load_segments()
            return gr.Audio(value=str(Pipeline(proj, log=lambda m: None).line_original_audio(segs[int(idx)])),
                            visible=True)

        def do_play_km(proj_v, idx, km, voice):
            if not (km or "").strip():
                raise gr.Error("This line has no Khmer text yet.")
            proj = project_from_dir(proj_v)
            sg = proj.load_segments()[int(idx)]
            info = _report(proj)["lines"].get(sg.id, {})
            same = (km or "").strip() == sg.km.strip() and voice == sg.voice and info.get("status") not in (
                "changed", "none", None)
            rate = info.get("rate") if same else sg.rate  # the fitted speed when nothing changed
            try:
                return gr.Audio(value=str(Pipeline(proj, log=lambda m: None).line_khmer_audio(km, voice, rate)),
                                visible=True)
            except Exception as e:
                raise gr.Error(_friendly(e)) from e

        play_zh.click(do_play_zh, [proj_dir, line_idx, editor_for], [line_audio])
        play_km.click(do_play_km, [proj_dir, line_idx, km_text, line_voice], [line_audio],
                      show_progress_on=[line_audio])

        def do_play_video(proj_v, idx, km, voice, bound, progress=gr.Progress()):
            if not _bound(bound, str(project_from_dir(proj_v).dir), idx):
                return not_picked(gr.update())
            if not (km or "").strip():
                raise gr.Error("This line has no Khmer text yet.")
            proj = _store(proj_v, idx, km, voice, False, bound)
            progress(0.3, desc="Making a short clip of this line")
            try:
                out = Pipeline(proj, log=lambda m: None).line_preview(int(idx))
            except Exception as e:
                raise gr.Error(_friendly(e)) from e
            return gr.Video(value=str(out), visible=True)

        play_vid.click(do_play_video, [proj_dir, line_idx, km_text, line_voice, editor_for], [line_video],
                       show_progress_on=[line_video])

        def do_make_voices(d, progress=gr.Progress()):
            proj = project_from_dir(d[proj_dir])
            if not proj.has_segments():
                raise gr.Error("There are no lines yet. Press Start in Settings first.")
            s = settings_from(d, proj)

            pipes: list = []

            def work(log, prog):
                pipes.append(Pipeline(proj, s, None, log, prog))
                return pipes[-1].build_audio(prog)

            text = ""
            for text, msg, _done, _res, err in run_in_background(work, progress):
                yield {head: header_html(proj, msg), log_box: text}
            if err:
                yield {head: header_html(proj), log_box: text}
                if _stopped(err):
                    return
                raise gr.Error(_friendly(err))
            gr.Info("Voices made. Lines marked in red run over the character; fix them with the timing tools.")
            _warn(pipes)
            out = refresh_editor(d, proj)
            out.update({head: header_html(proj), log_box: text, table: table_value(proj, int(d[line_idx] or 0),
                                                                              d[only_fix]),
                        weft: weft_html(proj, int(d[line_idx] or 0)), sync_info: sync_html(proj),
                        **rail_state("review", proj)})
            yield out

        make_voices_btn.click(do_make_voices, {proj_dir, line_idx, editor_for, only_fix, boxes, *setting_comps},
                              list(dict.fromkeys([*line_out, *editor_comps, head, log_box, *rail_list])),
                              show_progress_on=[sync_info], **HEAVY)

        def do_replace(proj_v, find, repl, idx, bound, only):
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
            return refresh_editor({editor_for: bound, line_idx: idx, only_fix: only}, proj) | {
                table: table_value(proj, idx, only)}

        replace_btn.click(do_replace, [proj_dir, find_txt, repl_txt, line_idx, editor_for, only_fix],
                          list(dict.fromkeys([*line_out, *editor_comps])))

        def do_all_voice(proj_v, idx, bound, only, v):
            proj = project_from_dir(proj_v)
            segs = proj.load_segments()
            for sg in segs:
                sg.voice = v
            proj.save_segments(segs)
            proj.path("voices_mode.txt").write_text(proj.load_settings().voice_mode)
            return refresh_editor({editor_for: bound, line_idx: idx, only_fix: only}, proj) | {
                table: table_value(proj, idx, only), weft: weft_html(proj, idx)}

        voice_in = [proj_dir, line_idx, editor_for, only_fix]
        voice_out = list(dict.fromkeys([*line_out, *editor_comps]))
        all_sreymom.click(lambda p, i, b, o: do_all_voice(p, i, b, o, "sreymom"), voice_in, voice_out)
        all_piseth.click(lambda p, i, b, o: do_all_voice(p, i, b, o, "piseth"), voice_in, voice_out)

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
                                  _bgr(JADE), 2)
            for r in box_list or []:
                a, b = r.get("start"), r.get("end")
                active = a is None or b is None or a <= t <= b
                cv2.rectangle(frame, (int(r["x"] * W), int(r["y"] * H)),
                              (int((r["x"] + r["w"]) * W), int((r["y"] + r["h"]) * H)),
                              _bgr(TUR) if active else _bgr(SILK_3), 3)
            if pt:
                cv2.drawMarker(frame, (int(pt[0] * W), int(pt[1] * H)), _bgr(TUR), cv2.MARKER_CROSS, 26, 3)
            return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        blur_view_in = [proj_dir, blur_t, boxes, pending_pt, blur, blur_sample_fps]
        blur_t.release(draw_blur_frame, blur_view_in, [blur_img])
        rail["blur"].click(draw_blur_frame, blur_view_in, [blur_img])

        def go_blur(p, *a):
            return {**go("blur", p), blur_img: draw_blur_frame(p, *a)}

        to_blur.click(go_blur, blur_view_in, [tabs, blur_img, *rail_list])

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
                yield {scan_msg: "Automatic blur is off (Settings). Only your own boxes are used."}
                return

            def work(log, prog):
                return Pipeline(proj, s, None, log, prog).scan_text(prog)

            res = []
            for text, msg, _done, res, err in run_in_background(work, progress):
                yield {scan_msg: msg, head: header_html(proj, msg), log_box: text}
            if err:
                yield {scan_msg: _friendly(err), head: header_html(proj), log_box: text}
                if _stopped(err):
                    return
                raise gr.Error(_friendly(err))
            n_move = sum(1 for tr in res if not tr["static"])
            yield {scan_msg: f"Found {len(res)} pieces of Chinese text, {n_move} of them moving. Move the slider "
                             "to check them.",
                   head: header_html(proj), **rail_state("blur", proj),
                   blur_img: draw_blur_frame(d[proj_dir], d[blur_t], d[boxes], None, d[blur], d[blur_sample_fps])}

        scan_in = {proj_dir, blur_t, boxes, *setting_comps}
        scan_btn.click(do_scan, scan_in, [scan_msg, head, log_box, blur_img, *rail_list],
                       show_progress_on=[blur_img], **HEAVY)

        def do_preview(d, progress=gr.Progress()):
            proj = project_from_dir(d[proj_dir])
            s = settings_from(d, proj)

            def work(log, prog):
                return Pipeline(proj, s, None, log, prog).preview(float(d[blur_t] or 0))

            text, res = "", None
            for text, msg, _done, res, err in run_in_background(work, progress):
                yield {log_box: text, scan_msg: msg, head: header_html(proj, msg)}
            if err:
                yield {scan_msg: _friendly(err), head: header_html(proj), log_box: text}
                if _stopped(err):
                    return
                raise gr.Error(_friendly(err))
            yield {preview_vid: str(res), log_box: text, scan_msg: "", head: header_html(proj)}

        preview_btn.click(do_preview, scan_in, [preview_vid, log_box, scan_msg, head], show_progress_on=[preview_vid],
                          **HEAVY)
        to_export.click(lambda p: go("export", p), [proj_dir], [tabs, *rail_list], queue=False)

        # ---- export
        def do_make(d, progress=gr.Progress()):
            proj = project_from_dir(d[proj_dir])
            if not proj.has_segments():
                raise gr.Error("There is no translation yet. Press Start in Settings, or Do everything.")
            s = settings_from(d, proj)

            pipes: list = []

            def work(log, prog):
                pipes.append(Pipeline(proj, s, None, log, prog))
                return pipes[-1].produce()

            text, res = "", None
            for text, msg, _done, res, err in run_in_background(work, progress):
                yield {head: header_html(proj, msg), log_box: text}
            if err:
                yield {head: header_html(proj), log_box: text}
                if _stopped(err):
                    return
                raise gr.Error(_friendly(err))
            gr.Info("The Khmer video is ready.")
            _warn(pipes)
            yield {head: header_html(proj), log_box: text, result: str(res),
                   downloads: [str(p) for p in Pipeline(proj, s, log=lambda m: None).downloads()],
                   folder: str(proj.dir), **rail_state("export", proj)}

        make_btn.click(do_make, {proj_dir, boxes, *setting_comps}, [head, log_box, result, downloads, folder,
                                                                    *rail_list], show_progress_on=[result], **HEAVY)

        # ---- cut
        cut_every.change(lambda v: gr.update(visible=v == -1.0), [cut_every], [cut_custom])
        cut_src.change(lambda v: gr.update(visible=v == "original"), [cut_src], [cut_projects])

        def do_cut(proj_v, src, every, custom, a, b, as_projects):
            from .cut import cut

            proj = project_from_dir(proj_v)
            video = proj.output_video if src == "khmer" else proj.video
            if not video.exists():
                raise gr.Error("There is no Khmer video yet. Make it in Export first, or cut the original.")
            minutes = float(custom or 0) if every == -1.0 else float(every or 0)
            name = f"{proj.dir.name}_{'khmer' if src == 'khmer' else 'chinese'}"
            try:
                parts = cut(video, proj.path("parts"), minutes or None, a, b, name=name)
            except ValueError as e:
                raise gr.Error(str(e)) from e
            from .cut import EXACT_TRIM_MAX, lengths, parse_time

            msg = f"{len(parts)} part{'s' if len(parts) != 1 else ''} ready ({lengths(parts)})."
            start, end = parse_time(a), parse_time(b)
            split = minutes and (not end or end - (start or 0) > minutes * 60 + 1)
            if start and (split or not end or end - start > EXACT_TRIM_MAX):
                msg += " Long cuts are copied without re-encoding, so they can start a few seconds early."
            if as_projects and src == "original":
                names = [project_from_upload(str(p)).dir.name for p in parts]
                msg += f" Opened as projects: {', '.join(names)}. Pick one in Upload, or use Batch."
            return msg, [str(p) for p in parts], gr.update(choices=list_projects())

        cut_btn.click(do_cut, [proj_dir, cut_src, cut_every, cut_custom, cut_from, cut_to, cut_projects],
                      [cut_msg, cut_out, existing])

        # ---- batch
        def do_batch(d, progress=gr.Progress()):
            files = d.get(batch_files) or []
            if not files:
                raise gr.Error("Add one or more videos first.")
            rows = [[Path(f).name, "waiting"] for f in files]
            finished: list[str] = []
            key = d.get(api_key) or None
            current: dict = {"proj": None}  # the episode being made, for the header

            def work(log, prog):
                for i, f in enumerate(files):
                    rows[i][1] = "working"
                    try:
                        proj = project_from_upload(f)
                        current["proj"] = proj
                        s = settings_from(d, proj, [])

                        def p(fr, m, i=i):
                            prog((i + fr) / len(files), f"{i + 1}/{len(files)}: {m}")

                        pl = Pipeline(proj, s, key, log, p)
                        finished.append(str(pl.run_all()))
                        rows[i][1] = "done" + (" · some lines without voice (see log)" if pl.warnings else "")
                    except Exception as e:  # keep going with the next episode
                        rows[i][1] = f"failed: {_friendly(e)[:120]}"
                        log(f"{Path(f).name}: {e}")
                return finished

            text, err = "", None
            for text, msg, _done, _res, err in run_in_background(work, progress):
                yield {batch_table: [r[:] for r in rows], log_box: text, head: header_html(current["proj"], msg)}
            if isinstance(err, jobs.Stopped):
                for r in rows:
                    r[1] = {"working": "stopped", "waiting": "not started"}.get(r[1], r[1])
                _stopped(err)
            opened = d.get(proj_dir)
            yield {batch_table: rows, batch_out: finished or None, log_box: text,
                   existing: gr.update(choices=list_projects()),
                   head: header_html(project_from_dir(opened) if opened else None)}

        batch_btn.click(do_batch, {batch_files, api_key, proj_dir, boxes, *setting_comps},
                        [batch_table, batch_out, log_box, existing, head], show_progress_on=[batch_table], **HEAVY)

        # ---- updates
        def update_banner(use_cache: bool = True) -> dict:
            from . import updater

            done = updater.just_updated()
            if done:
                return {upd_row: gr.Row(visible=True), upd_btn: gr.Button(visible=False),
                        upd_later: gr.Button(value="OK"),
                        upd_msg: f"Khmer Dub is now **{done}**. "
                                 f"[What's new](https://github.com/{updater.REPO}/releases/tag/v{done})"}
            staged = updater.pending()
            if staged:
                return {upd_row: gr.Row(visible=True), upd_btn: gr.Button(visible=False),
                        upd_later: gr.Button(value="OK"),
                        upd_msg: f"Khmer Dub **{staged['version']}** is downloaded. Close this window and open "
                                 "Khmer Dub again to finish the update."}
            rel = updater.check(use_cache)
            if not rel:
                return {upd_row: gr.Row(visible=False)}
            first = next((ln.strip(" #*-") for ln in rel.notes.splitlines() if ln.strip(" #*-")), "")
            note = (first[:140] + "…") if len(first) > 140 else first
            if updater.is_git_checkout():
                return {upd_row: gr.Row(visible=True), upd_btn: gr.Button(visible=False),
                        upd_later: gr.Button(value="Later"),
                        upd_msg: f"Khmer Dub **{rel.version}** is available. This copy is a git folder: "
                                 f"update it with `git pull`. [What's new]({rel.page_url})"}
            return {upd_row: gr.Row(visible=True), upd_btn: gr.Button(visible=True), upd_later: gr.Button(value="Later"),
                    upd_msg: f"Khmer Dub **{rel.version}** is available. {html.escape(note)} "
                             f"[What's new]({rel.page_url})"}

        upd_out = [upd_row, upd_msg, upd_btn, upd_later]
        app.load(lambda: update_banner(True), None, upd_out, show_progress="hidden")

        def do_update(progress=gr.Progress()):
            from . import updater

            rel = updater.check(use_cache=True)
            if not rel:
                raise gr.Error("No new version found.")
            try:
                updater.stage(rel, lambda f, m: progress(f, desc=m))
            except Exception as e:
                raise gr.Error(f"The update could not be downloaded: {e}") from e
            return {upd_msg: f"Khmer Dub **{rel.version}** is downloaded. Close this window and open Khmer Dub "
                             "again to finish the update.",
                    upd_btn: gr.Button(visible=False), upd_later: gr.Button(value="OK")}

        upd_btn.click(do_update, None, [upd_msg, upd_btn, upd_later], show_progress_on=[upd_msg])
        upd_later.click(lambda: gr.Row(visible=False), None, [upd_row], queue=False)

        def do_check():
            out = update_banner(use_cache=False)
            shown = out[upd_row].visible if upd_row in out else False
            out[chk_msg] = ("A new version is available: see the bar at the top." if shown
                            else f"You have the newest version ({__version__}).")
            return out

        chk_btn.click(do_check, None, [*upd_out, chk_msg])

        # ---- open a project from the address bar: ?project=NAME&step=review&line=6 (bookmarkable)
        def on_open(request: gr.Request):
            q = dict(request.query_params) if request else {}
            name = q.get("project")
            if not name or not (PROJECTS / name).is_dir():
                return {head: gr.update()}
            proj = project_from_dir(PROJECTS / name)
            out = load_into_ui(proj)
            step = q.get("step", "upload")
            if step in rail:
                out.update(go(step, str(proj.dir)))
            if q.get("line", "").isdigit() and proj.has_segments():
                out.update(show_line(str(proj.dir), int(q["line"]) - 1))
            if step == "blur":
                out[blur_img] = draw_blur_frame(str(proj.dir), min(5.0, _duration(proj) / 3),
                                                proj.load_settings().blur_regions, None,
                                                proj.load_settings().blur, proj.load_settings().blur_sample_fps)
            return out

        app.load(on_open, None, list(dict.fromkeys([*load_out, tabs, *line_out, blur_img]))).then(
            None, None, None, js=scroll_js)

        # ---- simple API for scripts: one call, video in -> Khmer video + subtitles out
        def api_dub(video, translator_name="google", key="", voice="auto", blur_mode="chinese", subs="burn",
                    model_name="", provider_name="", base_url_value=""):
            from .translate import ENGINES, PROVIDERS

            allowed = {"translator": (translator_name, list(ENGINES)), "voice": (voice, ["auto", "sreymom", "piseth"]),
                       "blur": (blur_mode, ["chinese", "all", "off"]), "subtitles": (subs, ["burn", "soft", "none"]),
                       "provider": (provider_name or "openrouter", list(PROVIDERS))}
            for name, (value, options) in allowed.items():
                if value not in options:  # check first, so a typo is never saved into the project
                    raise gr.Error(f"Unknown {name} {value!r}. Use one of: {', '.join(options)}.")
            if not video:
                raise gr.Error("Send a video file.")
            proj = project_from_upload(video)
            s = proj.load_settings()
            s.translator, s.voice_mode, s.blur, s.subtitles = translator_name, voice, blur_mode, subs
            if translator_name != "google" and (model_name or provider_name or base_url_value):
                s.translator_model = model_name or s.translator_model
                s.translator_provider = provider_name or s.translator_provider
                s.translator_base_url = base_url_value or s.translator_base_url
            proj.save_settings(s)
            try:
                out = Pipeline(proj, s, key or None, log=lambda m: None).run_all()
            except Exception as e:  # give the caller the real reason, not Gradio's generic message
                raise gr.Error(_friendly(e)) from e
            srt = proj.path(f"{proj.video.stem}_khmer.srt")
            return str(out), str(srt) if srt.exists() else None

        with gr.Row(visible=False):
            a_video = gr.File(type="filepath")
            a_tr, a_key, a_voice = gr.Textbox("google"), gr.Textbox(""), gr.Textbox("auto")
            a_blur, a_subs = gr.Textbox("chinese"), gr.Textbox("burn")
            a_model, a_provider, a_base = gr.Textbox(""), gr.Textbox(""), gr.Textbox("")
            a_out_v, a_out_s = gr.File(), gr.File()
            a_btn = gr.Button()
        a_btn.click(api_dub, [a_video, a_tr, a_key, a_voice, a_blur, a_subs, a_model, a_provider, a_base],
                    [a_out_v, a_out_s], api_name="dub_video", **HEAVY)

    return app


HELP_MD = """
## Help <span class='kd-km'>ជំនួយ</span>

**The five steps**

1. **Upload** a Chinese video, or continue a saved project.
2. **Settings**: a starting point at the top is enough for most videos. Press **Start**.
3. **Review**: click a line, listen to the original and the Khmer, fix the text, choose Sreymom or Piseth,
   then **Save and next**. The band at the top shows the whole episode; faded blocks are not checked yet.
   **Check timing** makes the voices and marks lines that don't fit the character (red = runs over). Tick
   *Only lines to fix*, then use *Earlier / Later*, *Speed*, **Shorten** and **Play in video** on each one.
4. **Blur**: check the green boxes; click two corners on the picture to add your own.
5. **Export**: make the video and download it.

**Cut** splits a video into 10- or 15-minute parts for TikTok or Facebook, or cuts a long Chinese episode into
parts you can dub one at a time. Everything is saved in the `projects` folder, so you can stop and continue later.

**Which translator?**

| | Cost | Quality |
|---|---|---|
| Google Translate | free, no key | OK |
| Gemini | free key | good |
| OpenRouter, Groq | free key | good, depends on the model |
| DeepSeek | very cheap | good |
| Claude | paid, cents per episode | best |
| Ollama | free, runs on your computer | depends on your PC |
| NLLB offline | free | basic |

**Tips**

- To stop a long job, press **Stop** at the top, next to the progress. Finished steps are kept: press the same
  button again later to continue.
- A one-hour episode takes about two hours without a graphics card. Use **Do everything automatically** or
  **Batch** and let it run.
- Same name translated differently? Review → All lines → Find and Replace.
- Khmer voice too fast? Lower *Max voice speed-up* or *Speed* in Settings → More options.
- Chinese text not blurred? Set Scan to *Careful*, or add a box in Blur.

**For developers**

Every run can also be started from your own scripts while the app is open:

```python
from gradio_client import Client, handle_file

client = Client("http://localhost:7860/")
video, srt = client.predict(handle_file("episode01.mp4"), "google", "", "auto", "chinese", "burn",
                            api_name="/dub_video")
# translator: google | gemini | custom | claude | openai | nllb   (then the API key)
# voice: auto | sreymom | piseth    blur: chinese | all | off    subtitles: burn | soft | none
# optional after those: model, provider (openrouter | groq | deepseek | ollama | other), base URL
```

Command line: `uv run --extra cpu khmerdub run video.mp4 --help` and `khmerdub cut video.mp4 --every 15`.
"""


# the header's Stop button is plain HTML (it is redrawn every second): pass its click to the hidden app button
STOP_JS = """<script>
document.addEventListener('click', function (e) {
  var b = e.target.closest ? e.target.closest('.kd-stop') : null;
  if (!b) return;
  e.preventDefault();
  b.disabled = true;
  b.textContent = 'Stopping…';
  var t = document.getElementById('kd-stop-btn');
  if (t) t.click();
});
</script>"""


def launch(port: int | None = 7860, share: bool = False, projects_dir: str | None = None,
           inbrowser: bool = True, window: bool = False) -> None:
    """Start the app. window=True shows it in its own app window and stops when that window closes."""
    global PROJECTS
    if projects_dir:
        PROJECTS = Path(projects_dir)
    PROJECTS.mkdir(parents=True, exist_ok=True)
    PROJECTS = PROJECTS.resolve()
    from .desktop import ICON_PNG

    app = build_app()
    app.queue(default_concurrency_limit=1).launch(
        server_port=port, share=share, inbrowser=inbrowser and not window,
        allowed_paths=[str(PROJECTS), str(FONTS.resolve())], favicon_path=str(ICON_PNG),
        theme=hol_theme(), css=build_css(), head=STOP_JS, max_file_size="20gb", prevent_thread_lock=window,
        quiet=window,
    )
    if not window:
        return
    from .desktop import open_window

    print("Khmer Dub is starting in its own window. Keep this black window open; closing the app window stops it.")
    how = open_window(app.local_url)
    if how in ("handed-off", "browser"):
        app.block_thread()  # can't see the window close: run until this console is closed or Ctrl+C
    app.close()
