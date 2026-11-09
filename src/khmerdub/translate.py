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
import time
from typing import Callable

from .project import Segment

ENGINES = {
    "google": "Google Translate (free)",
    "claude": "Claude – Anthropic (best quality, API key)",
    "openai": "ChatGPT – OpenAI (API key)",
    "gemini": "Gemini – Google AI (API key)",
    "nllb": "NLLB offline (free, no internet, slower)",
}
DEFAULT_MODELS = {
    "claude": "claude-opus-5-5",
    "openai": "gpt-5-mini",
    "gemini": "gemini-2.5-flash",
    "nllb": "facebook/nllb-200-distilled-600M",
}
KEY_ENV = {"claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}

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


def _openai(prompt: str, model: str, key: str | None) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=key) if key else OpenAI()
    resp = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
    )
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


def _llm(engine: str, segs: list[Segment], all_segs: list[Segment], model: str,
         key: str | None, progress: Progress | None, batch_size: int = 50) -> None:
    call = LLM_CALLS[engine]
    done = 0
    for i in range(0, len(segs), batch_size):
        batch = segs[i:i + batch_size]
        first = all_segs.index(batch[0])
        context = [s for s in all_segs[max(0, first - 12):first] if s.km]
        raw = _retry(lambda: call(_payload(batch, context), model, key), what=engine)
        try:
            data = json.loads(raw)
            got = {int(t["id"]): str(t["km"]).strip() for t in data["translations"]}
        except Exception as e:
            raise RuntimeError(f"{engine} returned something that is not the expected JSON: {raw[:300]}") from e
        for s in batch:
            if got.get(s.id):
                s.km = got[s.id]
        missing = [s for s in batch if not s.km]
        if missing:  # rare: model skipped some ids -> fill with Google
            _google(missing, None)
        done += len(batch)
        if progress:
            progress(done / len(segs), f"Translating ({engine})… {done}/{len(segs)}")


# ---------------------------------------------------------------- NLLB -------
def _nllb(segs: list[Segment], model: str, progress: Progress | None) -> None:
    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    from .devices import torch_device

    dev = torch_device()
    tok = AutoTokenizer.from_pretrained(model, src_lang="zho_Hans")
    net = AutoModelForSeq2SeqLM.from_pretrained(model).to(dev).eval()
    bos = tok.convert_tokens_to_ids("khm_Khmr")
    for i in range(0, len(segs), 16):
        batch = segs[i:i + 16]
        enc = tok([s.zh for s in batch], return_tensors="pt", padding=True).to(dev)
        with torch.no_grad():
            out = net.generate(**enc, forced_bos_token_id=bos, max_new_tokens=200, num_beams=4)
        for s, km in zip(batch, tok.batch_decode(out, skip_special_tokens=True)):
            s.km = km.strip()
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
) -> None:
    """Fill `km` for every segment that doesn't have it yet (in place)."""
    todo = [s for s in segs if s.zh.strip() and not s.km.strip()]
    if not todo:
        return
    if engine not in ENGINES:
        raise ValueError(f"Unknown translator {engine!r}. Choose from: {', '.join(ENGINES)}")
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
        _llm(engine, todo, segs, model, key, progress)
