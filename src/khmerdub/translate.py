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
    "gemini": "gemini-3.6-flash",  # if Google retires it, the newest Flash the key can use is picked
    "nllb": "facebook/nllb-200-distilled-600M",
}
KEY_ENV = {"claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}

# OpenAI-compatible services for the "custom" engine: name -> (base URL, key env var, suggested model, note)
PROVIDERS = {
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "google/gemma-4-31b-it:free",
                   "Free key at openrouter.ai; models ending in ':free' cost nothing"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "openai/gpt-oss-120b",
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
# Two free Google Translate addresses with separate limits. The first takes many lines in one request and
# returns exactly one translation per line; the second (the classic one) is the backup.
GOOGLE_LINES_URL = "https://clients5.google.com/translate_a/t"
GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"
GOOGLE_WAITS = (15, 30, 60, 90)  # seconds to wait when Google says "too many requests" (about 3 minutes)
GOOGLE_BUSY = ("Google Translate is refusing requests from this computer for now (too many requests). Wait 10–30 "
               "minutes and press Start again: lines already translated are kept. Or choose Gemini (free key).")
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


class GoogleBusy(Exception):
    pass


def _check(r) -> None:
    if r.status_code in (429, 503):  # 503 is Google's "unusual traffic" page
        raise GoogleBusy(r.headers.get("Retry-After") or "")
    r.raise_for_status()


def _google_lines(lines: list[str]) -> list[str]:
    import requests

    r = requests.post(GOOGLE_LINES_URL, params={"client": "dict-chrome-ex", "sl": "zh-CN", "tl": "km"},
                      data=[("q", x) for x in lines], headers=_HEADERS, timeout=30)
    _check(r)
    out = r.json()
    out = [x if isinstance(x, str) else (x[0] if x else "") for x in (out if isinstance(out, list) else [out])]
    if len(out) != len(lines):
        raise ValueError("Google returned a different number of lines")
    return [x.strip() for x in out]


def _google_text(text: str) -> str:
    import requests

    r = requests.post(GOOGLE_URL, params={"client": "gtx", "sl": "zh-CN", "tl": "km", "dt": "t"},
                      data={"q": text}, headers=_HEADERS, timeout=30)
    _check(r)
    return "".join(p[0] for p in r.json()[0] if p and p[0])


def _google_classic(lines: list[str]) -> list[str]:
    out = [x.strip() for x in _google_text("\n".join(lines)).split("\n")]
    if len(out) == len(lines):
        return out
    result = []  # the line count changed: one request per line
    for x in lines:
        result.append(_google_text(x).strip())
        time.sleep(0.2)
    return result


def _google_batch(lines: list[str], wait: Callable[[float, str], None]) -> list[str]:
    """Translate lines with whichever free Google address answers; wait it out when both are busy."""
    for attempt in range(len(GOOGLE_WAITS) + 1):
        busy, retry_after, error = False, 0, None
        for fn in (_google_lines, _google_classic):
            try:
                return fn(lines)
            except GoogleBusy as e:
                busy, retry_after = True, max(retry_after, int(str(e)) if str(e).isdigit() else 0)
            except Exception as e:  # network hiccup or an unexpected reply: try the other address
                error = e
        if attempt < len(GOOGLE_WAITS):
            wait(max(GOOGLE_WAITS[attempt], min(retry_after, 300)),
                 "Google Translate is busy" if busy else "Google Translate did not answer")
    if busy:
        raise RuntimeError(GOOGLE_BUSY)
    raise RuntimeError(f"Google Translate did not answer ({type(error).__name__}). Check the internet connection "
                       "and press Start again: lines already translated are kept.") from error


def _google(segs: list[Segment], progress: Progress | None) -> None:
    batches, cur, size = [], [], 0
    for s in segs:  # requests of at most 100 lines / ~3000 characters
        line = s.zh.replace("\n", " ")
        if cur and (size + len(line) + 1 > 3000 or len(cur) >= 100):
            batches.append(cur)
            cur, size = [], 0
        cur.append(s)
        size += len(line) + 1
    if cur:
        batches.append(cur)

    def wait(seconds: float, why: str) -> None:
        end = time.time() + seconds
        while time.time() < end:  # in small steps, so Stop still works while waiting
            if progress:
                progress(done / len(segs), f"{why}; trying again in {int(end - time.time()) + 1} s…")
            time.sleep(1)

    done = 0
    for batch in batches:
        out = _google_batch([s.zh.replace("\n", " ") for s in batch], wait)
        for s, km in zip(batch, out):
            s.km = km
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

OPENROUTER_ANY_FREE = "openrouter/free"  # OpenRouter's own router to whichever free model is available
_GONE_WORDS = ("not_found", "model_not_found", "no longer available", "does not exist", "decommissioned",
               "not a valid model", "unknown model", "model not found", "has been deprecated", "is not supported")


def _model_gone(e: BaseException) -> bool:
    """The service says this model doesn't exist (any more)."""
    status = (getattr(e, "status_code", None) or getattr(e, "code", None)
              or getattr(getattr(e, "response", None), "status_code", None))
    return status == 404 or any(w in str(e).lower() for w in _GONE_WORDS)


def _gemini_models(key: str | None) -> list[str]:
    from google import genai

    client = genai.Client(api_key=key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    names = []
    for m in client.models.list():
        actions = getattr(m, "supported_actions", None) or []
        if not actions or "generateContent" in actions:
            names.append((m.name or "").removeprefix("models/"))
    return names


def _newest_gemini_flash(names: list[str]) -> str | None:
    skip = ("lite", "image", "tts", "live", "audio", "embed", "exp", "thinking", "robotics", "native", "latest",
            "computer", "customtools")
    flash = [n for n in names if "flash" in n and not any(w in n for w in skip)]
    pool = [n for n in flash if "preview" not in n] or flash

    def version(n: str) -> float:
        m = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        return float(m.group(1)) if m else 0.0

    return max(pool, key=version) if pool else None


def _available_models(engine: str, key: str | None, base_url: str | None) -> list[str]:
    try:
        if engine == "gemini":
            return _gemini_models(key)
        if engine == "claude":
            import anthropic

            client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
            return [m.id for m in client.models.list()]
        from openai import OpenAI

        listed = list(OpenAI(api_key=key or "none", base_url=base_url or None).models.list())
        listed.sort(key=lambda m: getattr(m, "created", 0) or 0, reverse=True)
        return [m.id for m in listed]
    except Exception:
        return []


def _replacement(engine: str, provider: str, label: str, model: str, key: str | None, base_url: str | None,
                 err: BaseException) -> str:
    """A current model to use instead of a retired one, or a clear error naming some that work."""
    if engine == "gemini":
        new = _newest_gemini_flash(_available_models("gemini", key, None))
        if new and new != model:
            return new
    if engine == "custom" and provider == "openrouter" and model != OPENROUTER_ANY_FREE:
        return OPENROUTER_ANY_FREE
    names = _available_models(engine, key, base_url)
    hint = f" It offers for example: {', '.join(names[:8])}." if names else ""
    raise RuntimeError(f"{label} no longer offers the model '{model}' (or the API address is wrong). Type a "
                       f"current model name in Settings → More options → Model.{hint}") from err


def _ask(call, prompt: str, model: str, key: str | None, engine: str, provider: str, label: str,
         base_url: str | None, log: Callable[[str], None]) -> tuple[str, str]:
    """Ask the AI. If the service retired the model, switch to a current one. Returns (reply, model used)."""
    try:
        return _retry(lambda: call(prompt, model, key), what=label), model
    except Exception as e:
        if not _model_gone(e):
            raise
        new = _replacement(engine, provider, label, model, key, base_url, e)
        log(f"{label}: the model {model} is no longer offered; using {new} instead (change it in Settings).")
        return _retry(lambda: call(prompt, new, key), what=label), new


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
         label: str = "", provider: str = "", log: Callable[[str], None] = print) -> None:
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
        raw, model = _ask(call, _payload(batch, context), model, key, engine, provider, label, base_url, log)
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
             label=provider if engine == "custom" else engine, provider=provider, log=log)


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
    raw, _ = _ask(call, prompt, model, key, engine, provider, label, base_url or None, lambda m: None)
    try:
        out = str(_extract_json(raw)["translations"][0]["km"]).strip()
    except Exception as e:
        raise RuntimeError(f"{label} did not return a shorter line: {raw[:200]}") from e
    if not out:
        raise RuntimeError("The AI returned an empty line.")
    return out
