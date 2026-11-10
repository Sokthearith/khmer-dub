"""Chinese -> Khmer translation with several selectable engines.

    google  Google Translate        free, no key, fast, literal
    claude  Claude (Anthropic)      best quality, needs ANTHROPIC_API_KEY
    openai  ChatGPT (OpenAI)        needs OPENAI_API_KEY      (extra: openai)
    gemini  Gemini (Google AI)      needs GEMINI_API_KEY      (extra: gemini)
    nllb    NLLB-200 offline        free, private, no internet after model download (extra: offline)

Only lines whose Khmer text is still empty are translated, so re-running resumes.
LLM engines translate in batches with the previous lines as context, so names and
tone stay consistent across a 1-hour episode.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Callable

from .project import Segment

ENGINES = {
    "google": "Google Translate (free, no key)",
    "gemini": "Gemini – Google AI (free key)",
    "custom": "Other AI service – OpenRouter / Groq / DeepSeek / Ollama",
    "claude": "Claude – Anthropic (best quality, paid key)",
    "openai": "ChatGPT – OpenAI (paid key)",
    "nllb": "NLLB offline (free, no internet, basic)",
}
DEFAULT_MODELS = {
    "claude": "claude-opus-5-5",
    "openai": "gpt-5-mini",
    "gemini": "gemini-2.5-flash",
    "nllb": "facebook/nllb-200-distilled-600M",
}
KEY_ENV = {"claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}

# OpenAI-compatible services for the "custom" engine: name -> (base URL, key env var, suggested model, note)
PROVIDERS = {
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "deepseek/deepseek-chat-v3-0324:free",
                   "Free key at openrouter.ai; models ending in ':free' cost nothing"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "llama-3.3-70b-versatile",
             "Free key at console.groq.com; very fast"),
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY", "deepseek-chat",
                 "Key at platform.deepseek.com; very cheap, strong at Chinese"),
    "ollama": ("http://localhost:11434/v1", None, "qwen2.5:7b",
               "Runs on your computer (ollama.com), free and offline; needs a strong PC"),
    "other": ("", None, "", "Any OpenAI-compatible API: paste its base URL"),
}

Progress = Callable[[float, str], None]

SYSTEM_PROMPT = """You translate Chinese (Mandarin) TV drama / video dialogue into Khmer for a Khmer voice dub and Khmer subtitles.

Rules:
- Write natural, spoken, everyday Khmer as heard in Cambodian-dubbed Chinese dramas, not stiff written Khmer.
- Use pronouns and politeness that fit the relationship and tone suggested by context (e.g. បង/អូន, លោក/នាង, ខ្ញុំ/ឯង).
- Transliterate Chinese personal names into Khmer script and keep each name identical every time it appears.
- Keep each line short enough to be spoken in the given number of seconds (about 4–6 Khmer syllables per second). Shorten wording rather than drop meaning.
- The Chinese comes from speech recognition and can contain wrong characters; use context to infer the intended meaning.
- Translate every line separately; never merge or split lines. Return exactly one translation per input id.
- Output only Khmer text in the translation (no Chinese, no pinyin, no notes)."""

SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "km": {"type": "string"}},
                "required": ["id", "km"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["translations"],
    "additionalProperties": False,
}


_TRANSIENT = ("RateLimit", "Timeout", "Connection", "InternalServer", "Overloaded", "ServiceUnavailable",
              "HTTPError", "ServerError", "TooManyRequests", "DeadlineExceeded")


def _retry(fn, tries: int = 4, what: str = "request"):
    """Retry network hiccups / rate limits; fail fast on wrong keys or bad requests."""
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            name = type(e).__name__
            status = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
            transient = any(t in name for t in _TRANSIENT) or status in (408, 429, 500, 502, 503, 504, 529)
            if status in (401, 403) or "authentication" in str(e).lower() or "api key" in str(e).lower():
                raise RuntimeError(f"{what}: the API key is missing or wrong. Paste a valid key in the app "
                                   f"(or set the environment variable). Details: {str(e)[:200]}") from e
            if not transient or i == tries - 1:
                raise
            time.sleep(2 * (i + 1) ** 2)
    raise RuntimeError(what)


# ---------------------------------------------------------------- Google -----
GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"


def _google_text(text: str) -> str:
    import requests

    r = requests.post(GOOGLE_URL, params={"client": "gtx", "sl": "zh-CN", "tl": "km", "dt": "t"},
                      data={"q": text}, timeout=30)
    r.raise_for_status()
    return "".join(p[0] for p in r.json()[0] if p and p[0])


def _google(segs: list[Segment], progress: Progress | None) -> None:
    batches, cur, size = [], [], 0
    for s in segs:  # pack lines into requests of < 2000 chars, one line per row
        line = s.zh.replace("\n", " ")
        if cur and (size + len(line) + 1 > 2000 or len(cur) >= 100):
            batches.append(cur)
            cur, size = [], 0
        cur.append(s)
        size += len(line) + 1
    if cur:
        batches.append(cur)

    done = 0
    for batch in batches:
        text = "\n".join(s.zh.replace("\n", " ") for s in batch)
        out = _retry(lambda: _google_text(text)) or ""
        lines = [x.strip() for x in out.split("\n")]
        if len(lines) == len(batch):
            for s, km in zip(batch, lines):
                s.km = km
        else:  # line count changed: fall back to one request per line
            for s in batch:
                s.km = (_retry(lambda: _google_text(s.zh)) or "").strip()
                time.sleep(0.2)
        done += len(batch)
        time.sleep(0.5)
        if progress:
            progress(done / len(segs), f"Translating (Google)… {done}/{len(segs)}")


# ---------------------------------------------------------------- LLMs -------
def _payload(batch: list[Segment], context: list[Segment]) -> str:
    parts = []
    if context:
        parts.append("Previous lines (already translated, for context only):")
        parts += [f"- {c.zh} => {c.km}" for c in context]
        parts.append("")
    parts.append("Translate these lines. Reply as JSON {\"translations\": [{\"id\": ..., \"km\": ...}]}.")
    parts.append(json.dumps(
        [{"id": s.id, "zh": s.zh, "seconds": round(s.duration, 1)} for s in batch],
        ensure_ascii=False,
    ))
    return "\n".join(parts)


def _claude(prompt: str, model: str, key: str | None) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
    resp = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        # If a line trips a safety filter, the API retries on a fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude declined this batch")
    return next(b.text for b in resp.content if b.type == "text")


def _openai(prompt: str, model: str, key: str | None, base_url: str | None = None) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=key or ("none" if base_url else None), base_url=base_url or None)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
    try:
        resp = client.chat.completions.create(model=model, response_format={"type": "json_object"},
                                              messages=messages)
    except Exception as e:  # some services don't support JSON mode: ask without it
        if "response_format" not in str(e) and "json" not in str(e).lower():
            raise
        resp = client.chat.completions.create(model=model, messages=messages)
    return resp.choices[0].message.content or ""


def _gemini(prompt: str, model: str, key: str | None) -> str:
    from google import genai

    client = genai.Client(api_key=key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config={"system_instruction": SYSTEM_PROMPT, "response_mime_type": "application/json"},
    )
    return resp.text or ""


LLM_CALLS = {"claude": _claude, "openai": _openai, "gemini": _gemini}


def _extract_json(raw: str) -> dict:
    """Parse JSON even if the model wrapped it in ```json fences or added a sentence."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        a, b = raw.find("{"), raw.rfind("}")
        if a >= 0 and b > a:
            return json.loads(raw[a:b + 1])
        raise


def _llm(engine: str, segs: list[Segment], all_segs: list[Segment], model: str,
         key: str | None, progress: Progress | None, batch_size: int = 50, base_url: str | None = None,
         label: str = "") -> None:
    label = label or engine  # the name people know: "groq", not "custom"
    if engine == "custom":
        call = lambda prompt, m, k: _openai(prompt, m, k, base_url)  # noqa: E731
    else:
        call = LLM_CALLS[engine]
    done = 0
    for i in range(0, len(segs), batch_size):
        batch = segs[i:i + batch_size]
        first = all_segs.index(batch[0])
        context = [s for s in all_segs[max(0, first - 12):first] if s.km]
        raw = _retry(lambda: call(_payload(batch, context), model, key), what=label)
        try:
            data = _extract_json(raw)
            got = {int(t["id"]): str(t["km"]).strip() for t in data["translations"]}
        except Exception as e:
            raise RuntimeError(f"{label} returned something that is not the expected JSON: {raw[:300]}") from e
        for s in batch:
            if got.get(s.id):
                s.km = got[s.id]
        missing = [s for s in batch if not s.km]
        if missing:  # rare: model skipped some ids -> fill with Google
            _google(missing, None)
        done += len(batch)
        if progress:
            progress(done / len(segs), f"Translating ({label})… {done}/{len(segs)}")


# ---------------------------------------------------------------- NLLB -------
KHMER_GAP = re.compile(r"(?<=[\u1780-\u17ff]) +(?=[\u1780-\u17ff])")


def _nllb(segs: list[Segment], model: str, progress: Progress | None) -> None:
    import torch

    try:
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    except ImportError as e:
        raise RuntimeError("The offline translator is not installed. Start Khmer Dub with its start script "
                           "(it installs it), or choose Google Translate.") from e

    from .devices import torch_device

    dev = torch_device()
    tok = AutoTokenizer.from_pretrained(model, src_lang="zho_Hans")
    try:  # the .bin weights only: otherwise transformers fetches a second 2.4 GB copy in the background
        net = AutoModelForSeq2SeqLM.from_pretrained(model, use_safetensors=False)
    except (OSError, ValueError):  # a model published only as .safetensors
        net = AutoModelForSeq2SeqLM.from_pretrained(model)
    net = net.to(dev).eval()
    bos = tok.convert_tokens_to_ids("khm_Khmr")
    for i in range(0, len(segs), 16):
        batch = segs[i:i + 16]
        enc = tok([s.zh for s in batch], return_tensors="pt", padding=True).to(dev)
        with torch.no_grad():
            out = net.generate(**enc, forced_bos_token_id=bos, max_new_tokens=200, num_beams=4)
        for s, km in zip(batch, tok.batch_decode(out, skip_special_tokens=True)):
            # NLLB puts spaces between Khmer words; Khmer writes them together (invisible word breaks)
            s.km = KHMER_GAP.sub("\u200b", km.strip())
        if progress:
            progress(min(1, (i + 16) / len(segs)), f"Translating (offline)… {min(i + 16, len(segs))}/{len(segs)}")


# ---------------------------------------------------------------- entry ------
def translate(
    segs: list[Segment],
    engine: str = "google",
    model: str = "",
    api_key: str | None = None,
    progress: Progress | None = None,
    log: Callable[[str], None] = print,
    provider: str = "openrouter",
    base_url: str = "",
) -> None:
    """Fill `km` for every segment that doesn't have it yet (in place)."""
    todo = [s for s in segs if s.zh.strip() and not s.km.strip()]
    if not todo:
        return
    if engine not in ENGINES:
        raise ValueError(f"Unknown translator {engine!r}. Choose from: {', '.join(ENGINES)}")
    if engine == "custom":
        url, env, suggested, _ = PROVIDERS.get(provider, PROVIDERS["other"])
        base_url = base_url or url
        model = model or suggested
        key = api_key or (os.environ.get(env) if env else None)
        if not base_url:
            raise RuntimeError("Paste the API address (base URL) of the AI service.")
        if not model:
            raise RuntimeError("Type the model name to use.")
        if env and not key:
            raise RuntimeError(f"{provider} needs an API key (paste it in the app or set {env}).")
    else:
        model = model or DEFAULT_MODELS.get(engine, "")
        key = api_key or (os.environ.get(KEY_ENV[engine]) if engine in KEY_ENV else None)
    log(f"Translating {len(todo)} lines with {ENGINES[engine]}" + (f" [{model}]" if model else ""))

    if engine == "google":
        _google(todo, progress)
    elif engine == "nllb":
        _nllb(todo, model, progress)
    else:
        if engine in ("openai", "gemini") and not key:
            raise RuntimeError(f"{ENGINES[engine]} needs an API key (set {KEY_ENV[engine]} or paste it in the app).")
        _llm(engine, todo, segs, model, key, progress, base_url=base_url or None,
             label=provider if engine == "custom" else engine)


# ---------------------------------------------------------------- shorten ----
def shorten(zh: str, km: str, seconds: float, engine: str, model: str = "", api_key: str | None = None,
            provider: str = "openrouter", base_url: str = "") -> str:
    """Rewrite one Khmer line shorter so it can be spoken naturally in `seconds` (AI translators only)."""
    if engine not in LLM_CALLS and engine != "custom":
        raise RuntimeError("Shorten needs an AI translator, for example Gemini with a free key. "
                           "Choose one in Settings, then try again.")
    if engine == "custom":
        url, env, suggested, _ = PROVIDERS.get(provider, PROVIDERS["other"])
        base_url, model = base_url or url, model or suggested
        key = api_key or (os.environ.get(env) if env else None)
        call = lambda prompt, m, k: _openai(prompt, m, k, base_url)  # noqa: E731
    else:
        model = model or DEFAULT_MODELS.get(engine, "")
        key = api_key or os.environ.get(KEY_ENV[engine])
        if engine in ("openai", "gemini") and not key:
            raise RuntimeError(f"{ENGINES[engine]} needs an API key (paste it in Settings).")
        call = LLM_CALLS[engine]
    syllables = max(3, round(seconds * 5))
    prompt = (f"This Khmer dubbing line is too long to say in {seconds:.1f} seconds.\n"
              f"Chinese original: {zh}\nCurrent Khmer: {km}\n"
              f"Rewrite the Khmer so it keeps the meaning, tone and names, but can be spoken naturally in about "
              f"{seconds:.1f} seconds (about {syllables} Khmer syllables). Spoken, everyday Khmer.\n"
              'Reply as JSON {"translations": [{"id": 0, "km": "..."}]}.')
    label = provider if engine == "custom" else engine
    raw = _retry(lambda: call(prompt, model, key), what=label)
    try:
        out = str(_extract_json(raw)["translations"][0]["km"]).strip()
    except Exception as e:
        raise RuntimeError(f"{label} did not return a shorter line: {raw[:200]}") from e
    if not out:
        raise RuntimeError("The AI returned an empty line.")
    return out
