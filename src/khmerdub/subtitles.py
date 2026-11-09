"""Khmer subtitles: SRT (for sharing/YouTube) and ASS (styled, burned into the video).

Khmer is usually written without spaces between words, so line wrapping can't rely
on spaces alone. We prefer spaces / zero-width spaces and otherwise break at a
syllable-cluster boundary (never inside a stacked consonant).
"""

from __future__ import annotations

import re
from pathlib import Path

from .project import Segment

COENG = "្"
ZWSP = "​"


def _ts_srt(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ts_ass(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _is_cluster_start(text: str, i: int) -> bool:
    c = text[i]
    base = "ក" <= c <= "ឳ"  # consonants + independent vowels
    return base and i > 0 and text[i - 1] != COENG


def visual_len(text: str) -> int:
    """Approximate on-screen width in 'base characters' (marks/subscripts take no width)."""
    return sum(1 for i, c in enumerate(text)
               if not ("឴" <= c <= "៓" or c == ZWSP or (i > 0 and text[i - 1] == COENG)))


def wrap_khmer(text: str, max_len: int) -> list[str]:
    text = " ".join(text.split())
    if visual_len(text) <= max_len:
        return [text]
    n_lines = -(-visual_len(text) // max_len)
    target = visual_len(text) / n_lines
    lines, rest = [], text
    while visual_len(rest) > max_len:
        # candidate break positions with their visual offset
        best, best_score = None, None
        vis = 0
        for i in range(1, len(rest)):
            vis = visual_len(rest[:i])
            if vis > max_len:
                break
            c = rest[i]
            if c in (" ", ZWSP):
                kind = 0  # preferred
            elif _is_cluster_start(rest, i) or (rest[i - 1] in "។៕,.!?" ):
                kind = 1
            else:
                continue
            score = abs(vis - target) + (0 if kind == 0 else target * 0.25)
            if best_score is None or score < best_score:
                best, best_score = i, score
        if best is None:
            best = len(rest)
        lines.append(rest[:best].strip(" " + ZWSP))
        rest = rest[best:].strip(" " + ZWSP)
    if rest:
        lines.append(rest)
    return lines


def subtitle_lines(segs: list[Segment], timing: dict | None) -> list[tuple[float, float, str]]:
    out = []
    for s in sorted(segs, key=lambda x: x.start):
        if not s.km.strip():
            continue
        t = (timing or {}).get(str(s.id)) or (timing or {}).get(s.id)
        start, end = (t["start"], t["end"]) if t else (s.start, s.end)
        out.append([start, max(end, start + 0.8), s.km.strip()])
    for a, b in zip(out, out[1:]):  # no overlaps
        if a[1] > b[0]:
            a[1] = max(a[0] + 0.3, b[0] - 0.02)
    return [tuple(x) for x in out]


def write_srt(lines, path: Path, max_len: int = 42) -> None:
    blocks = []
    for i, (a, b, text) in enumerate(lines, 1):
        blocks.append(f"{i}\n{_ts_srt(a)} --> {_ts_srt(b)}\n" + "\n".join(wrap_khmer(text, max_len)) + "\n")
    path.write_text("\n".join(blocks), encoding="utf-8")


def write_zh_srt(segs: list[Segment], path: Path) -> None:
    blocks = [f"{i}\n{_ts_srt(s.start)} --> {_ts_srt(s.end)}\n{s.zh}\n" for i, s in enumerate(segs, 1)]
    path.write_text("\n".join(blocks), encoding="utf-8")


COLORS = {"white": "&H00FFFFFF", "yellow": "&H0000F0FF", "cyan": "&H00FFFF80"}


def write_ass(lines, path: Path, width: int, height: int, size: float = 1.0,
              font: str = "Noto Sans Khmer", offset: float = 0.0, position: str = "bottom",
              color: str = "white", box: bool = False) -> None:
    fs = round(min(height, width * 9 / 16) * 0.056 * size)
    outline = max(1.5, fs * 0.08)
    margin_v = round(height * 0.05)
    max_len = max(12, int(width * 0.88 / (fs * 0.62)))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{fs},{COLORS.get(color, COLORS["white"])},&H00FFFFFF,{"&H60000000" if box else "&H00000000"},{"&H60000000" if box else "&H64000000"},1,0,0,0,100,100,0,0,{3 if box else 1},{(fs * 0.18 if box else outline):.1f},{0 if box else 1},{8 if position == "top" else 2},{round(width * 0.05)},{round(width * 0.05)},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for a, b, text in lines:
        a, b = a - offset, b - offset
        if b <= 0:
            continue
        body = r"\N".join(wrap_khmer(text, max_len)).replace("{", "(").replace("}", ")")
        events.append(f"Dialogue: 0,{_ts_ass(a)},{_ts_ass(b)},Default,,0,0,0,,{body}")
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")


_SRT_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def read_srt(path: Path) -> list[tuple[float, float, str]]:
    """Parse an .srt file into (start, end, text)."""
    raw = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    out = []
    for block in re.split(r"\n\s*\n", raw.replace("\r\n", "\n")):
        rows = [r for r in block.strip().split("\n") if r.strip()]
        for j, r in enumerate(rows):
            m = _SRT_TIME.search(r)
            if m:
                g = [int(x) for x in m.groups()]
                a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                b = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                text = " ".join(rows[j + 1:]).strip()
                text = re.sub(r"<[^>]+>|\{[^}]+\}", "", text)
                if text:
                    out.append((a, b, text))
                break
    return out
