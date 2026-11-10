"""Find and blur on-screen text (by default only Chinese text).

Every piece of text found is sorted into one of three kinds, and the user picks which to blur
("What to blur"; by default subtitles and logos, not every sign or screen in the picture):

* subtitle: the burned-in Chinese subtitle lines (bottom, centred, changing). Each line gets its
  own tight box, only while it is on screen.
* logo: watermarks, channel names and banners (bilibili...): text that stays at an edge or corner,
  or scrolls across the frame. One fixed box (or one that follows the scrolling).
* other: text that is part of the animation itself (signs, screens, papers): left alone unless asked.

Moving / floating text: detections in consecutive samples are linked into a track and the
blur box is interpolated (and slightly extrapolated) between samples, so it follows the text.

Detection samples the video `sample_fps` times per second with the RapidOCR
(PaddleOCR) text detector, skipping frames that didn't change. The recognizer runs
only a few times per track to decide whether the text contains Chinese characters.
Manual boxes can be added for anything the detector misses.
"""

from __future__ import annotations

import bisect
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
DET_MAX_SIDE = 800
CACHE_VERSION = 2  # scans saved by older versions are redone (they had no kinds and merged subtitles)
TARGETS = {"subtitle": "subtitles", "logo": "logos", "other": "other"}  # kind -> "What to blur" choice
DEFAULT_TARGETS = ["subtitles", "logos"]
# words of watermarks / platform logos (also misread forms like "ilibli")
WATERMARKS = ("bili", "ilibl", "哔哩", "抖音", "douyin", "tiktok", "快手", "kuaishou", "腾讯", "优酷", "youku", "爱奇艺",
              "iqiyi", "芒果", "西瓜视频", "微博", "weibo", "小红书", "youtube", "漫剧", "短剧", "出品", "原创", "@")


def cache_name(mode: str, sample_fps: float) -> str:
    return f"blur_{mode}_{float(sample_fps):g}fps_v{CACHE_VERSION}.json"


def pick(tracks: list[dict], targets) -> list[dict]:
    """Only the kinds of text the user wants blurred (manual boxes always stay)."""
    want = set(targets if targets is not None else DEFAULT_TARGETS)
    return [t for t in tracks if t.get("text") == "manual" or TARGETS.get(t.get("kind", "other")) in want]


def _scrolls(k: np.ndarray, width: float, height: float) -> bool:
    """A banner: text sliding steadily one way along the top or bottom of the frame (not text that only
    seems to move because a tracker joined two different texts)."""
    cx, cy = (k[:, 1] + k[:, 3]) / 2, (k[:, 2] + k[:, 4]) / 2
    steps = np.diff(cx)
    moving = steps[np.abs(steps) > 0.5]
    if len(moving) < 3 or abs(cx[-1] - cx[0]) < 0.25 * width or np.ptp(cy) > 0.1 * height:
        return False
    one_way = max((moving > 0).mean(), (moving < 0).mean()) >= 0.8
    return one_way and (cy.mean() < 0.25 * height or cy.mean() > 0.75 * height)


def _kind(k: np.ndarray, text: str, moving: bool, chinese: bool, width: float, height: float) -> str:
    """subtitle | logo | other (see the module notes). k: samples [t, x0, y0, x1, y1]."""
    low = (text or "").lower().replace(" ", "")
    if any(w in low for w in WATERMARKS):
        return "logo"
    if moving:
        return "logo" if _scrolls(k, width, height) else "other"
    cx, cy = float((k[:, 1] + k[:, 3]).mean() / 2), float((k[:, 2] + k[:, 4]).mean() / 2)
    h, span = float(np.median(k[:, 4] - k[:, 2])), float(k[-1, 0] - k[0, 0])
    w = float(np.median(k[:, 3] - k[:, 1]))
    changing = np.ptp(k[:, 1]) > 0.5 * h or np.ptp(k[:, 3]) > 0.5 * h  # different lines in the same place
    low_centre = cy > 0.66 * height and abs(cx - width / 2) < 0.22 * width
    if low_centre and h <= 0.16 * height and w >= 2.2 * h and (changing or span < 8):  # a line of 2+ characters
        return "subtitle"
    at_edge = cx < 0.22 * width or cx > 0.78 * width or cy < 0.15 * height or cy > 0.85 * height
    if at_edge and span >= (6 if chinese else 20):  # stays put: a logo / channel name
        return "logo"
    return "other"


def _lines(k: np.ndarray, dt: float) -> list[np.ndarray]:
    """Split a subtitle track into its lines: a new line starts after a gap or where the text changes."""
    runs, cur = [], [k[0]]
    for a, b in zip(k[:-1], k[1:]):
        if b[0] - a[0] <= max(0.9, 2.5 * dt) and _iou(a[1:], b[1:]) > 0.6:
            cur.append(b)
        else:
            runs.append(np.array(cur))
            cur = [b]
    runs.append(np.array(cur))
    return runs


@dataclass
class _Track:
    keys: list[list[float]] = field(default_factory=list)  # [t, x0, y0, x1, y1]
    cjk: int = 0  # most Chinese characters read in this track
    checks: int = 0
    text: str = ""

    @property
    def last(self):
        return self.keys[-1]

    @property
    def chinese(self) -> bool:
        # 1 lone character is often a misread shape; accept it only if it stays on screen
        return self.cjk >= 2 or (self.cjk == 1 and len(self.keys) >= 3)

    def velocity(self) -> tuple[float, float]:
        """Average motion (px/s) over the last few samples; robust to box jitter."""
        if len(self.keys) < 2:
            return 0.0, 0.0
        a, b = self.keys[-min(4, len(self.keys))], self.keys[-1]
        d = max(b[0] - a[0], 1e-6)
        return ((b[1] + b[3]) - (a[1] + a[3])) / 2 / d, ((b[2] + b[4]) - (a[2] + a[4])) / 2 / d


def _iou(a, b) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _travels(keys, width: float = 0.0) -> bool:
    """True if the text really moves: its covered area is much bigger than the text itself, or it is
    scrolling in/out at the left or right edge of the frame (it grows or shrinks there instead of moving)."""
    if len(keys) < 2:
        return False
    k = np.asarray(keys)
    union = (k[:, 3].max() - k[:, 1].min()) * (k[:, 4].max() - k[:, 2].min())
    typical = np.median((k[:, 3] - k[:, 1]) * (k[:, 4] - k[:, 2]))
    if union > 3.0 * max(typical, 1.0):
        return True
    if width:
        h = float(np.median(k[:, 4] - k[:, 2]))
        at_right, at_left = (k[:, 3] >= width - 6).any(), (k[:, 1] <= 6).any()
        if (at_right and np.ptp(k[:, 1]) > 2 * h) or (at_left and np.ptp(k[:, 3]) > 2 * h):
            return True
    return False


def _follow_out(k: np.ndarray, width: float, scan_end: float, alive_at_end: bool) -> list[float] | None:
    """Keep a moving text's blur going after its last detection, along its motion, until it has left the
    frame (text sliding off an edge is hard to detect when only a sliver is left) or the video ends."""
    a, b = k[-min(4, len(k))], k[-1]
    d = b[0] - a[0]
    if d <= 0:
        return None
    v = (b[1:] - a[1:]) / d  # per-corner speed in px/s
    t_end = None
    if alive_at_end:
        t_end = scan_end
    elif b[1] <= 6 and v[2] < -1:  # leaving at the left edge: until its right side has gone
        t_end = b[0] + b[3] / -v[2]
    elif b[3] >= width - 6 and v[0] > 1:  # leaving at the right edge: until its left side has gone
        t_end = b[0] + (width - b[1]) / v[0]
    if t_end is None or t_end <= b[0] + 0.05:
        return None
    t_end = min(t_end, b[0] + 3.0)
    return [t_end, *(b[1:] + v * (t_end - b[0]))]


def _match_score(box, tr: _Track, t: float) -> float:
    """How likely detection `box` at time t continues track `tr` (0 = not at all)."""
    prev = tr.last[1:]
    h, ph = box[3] - box[1], prev[3] - prev[1]
    if not (0.7 < h / max(ph, 1) < 1.4):
        return 0.0
    vx, vy = tr.velocity()
    gap = t - tr.last[0]
    px, py = (prev[0] + prev[2]) / 2 + vx * gap, (prev[1] + prev[3]) / 2 + vy * gap  # predicted centre
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    dx, dy = abs(cx - px), abs(cy - py)
    moving = np.hypot(vx, vy) * max(gap, 0.2) > 0.6 * h
    iou = _iou(box, prev)
    if iou > 0.3:
        return 2 + iou  # overlapping: same text (still, slow, or a new subtitle line in the same spot)
    if moving:  # follow the motion: must be near where the text should be by now
        tol = 0.6 * h + 0.25 * np.hypot(vx, vy) * gap
        return 1.5 - np.hypot(dx, dy) / (3 * tol) if np.hypot(dx, dy) < tol else 0.0
    if len(tr.keys) >= 3:  # established still text doesn't suddenly jump away
        return 0.0
    # a brand-new track may start moving: allow a shift along one axis (scrolling)
    if dy < 0.5 * h and dx < 6 * h:
        return 1 - dx / (6 * h)
    if dx < 0.5 * h and dy < 3 * h:
        return 1 - dy / (3 * h)
    return 0.0


def _sampled_frames(video: Path, fps: float, w: int, h: int, start: float, end: float | None):
    """Let ffmpeg decode (multi-threaded), pick `fps` frames per second and shrink them."""
    from .media import read_frames

    yield from read_frames(video, start, (end - start) if end else None, fps, w, h, scale_flags="area")


def detect(
    video: Path,
    mode: str = "chinese",
    sample_fps: float = 3.0,
    start: float = 0.0,
    end: float | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> list[dict]:
    """Return blur tracks: [{"keys": [[t,x0,y0,x1,y1],...], "static": bool, "text": str}]."""
    import cv2
    from rapidocr_onnxruntime import RapidOCR

    from .media import video_info

    ocr = RapidOCR()
    info = video_info(video)
    W, H = info.width, info.height
    scale = min(1.0, DET_MAX_SIDE / max(W, H))
    sw, sh = max(2, round(W * scale / 2) * 2), max(2, round(H * scale / 2) * 2)
    sx, sy = W / sw, H / sh
    ocr.text_det.limit_type, ocr.text_det.limit_side_len = "max", max(sw, sh)  # never upscale
    end = min(end or info.duration, info.duration) if info.duration else end
    dt = 1.0 / sample_fps
    min_h_ratio = 0.012

    active: list[_Track] = []
    done: list[_Track] = []
    prev_thumb, prev_boxes = None, []

    def classify(tracks_imgs):
        if mode != "chinese" or not tracks_imgs:
            return
        crops = [c for _, c in tracks_imgs]
        res, _ = ocr.text_rec(crops)
        for (tr, _), (text, score) in zip(tracks_imgs, res):
            tr.checks += 1
            if text and len(text) > len(tr.text):
                tr.text = text
            if score > 0.4:
                tr.cjk = max(tr.cjk, len(CJK.findall(text or "")))

    t = start
    for n, small in enumerate(_sampled_frames(video, sample_fps, sw, sh, start, end)):
        t = start + n * dt
        thumb = cv2.cvtColor(cv2.resize(small, (160, 90), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.int16)
        if prev_thumb is not None and np.abs(thumb - prev_thumb).mean() < 1.0:
            boxes, quads = prev_boxes, []  # frame unchanged: reuse detections
        else:
            det, _ = ocr.text_det(small)
            boxes, quads = [], []
            for q in (det if det is not None else []):
                x0, y0 = q[:, 0].min() * sx, q[:, 1].min() * sy
                x1, y1 = q[:, 0].max() * sx, q[:, 1].max() * sy
                if (y1 - y0) >= max(8, H * min_h_ratio):
                    boxes.append([x0, y0, x1, y1])
                    quads.append(q)
            prev_boxes = boxes
        prev_thumb = thumb

        # link detections to tracks: best-scoring pairs first, each used once
        pairs = sorted(((sc, bi, ti) for bi, box in enumerate(boxes) for ti, tr in enumerate(active)
                        if (sc := _match_score(box, tr, t)) > 0), reverse=True)
        owner: dict[int, _Track] = {}
        taken = set()
        for sc, bi, ti in pairs:
            if bi not in owner and ti not in taken:
                owner[bi] = active[ti]
                taken.add(ti)
        to_check = []
        for bi, box in enumerate(boxes):
            tr = owner.get(bi)
            if tr is None:
                tr = _Track()
                active.append(tr)
            tr.keys.append([t, *box])
            k = len(tr.keys)
            if mode == "chinese" and quads and tr.cjk < 2 and tr.checks < 5 and k in (1, 2, 3, 6, 12, 30):
                to_check.append((tr, bi))

        if to_check:
            crops = ocr.get_crop_img_list(small, np.array([quads[bi] for _, bi in to_check], dtype=np.float32))
            classify([(tr, c) for (tr, _), c in zip(to_check, crops)])

        alive = []
        for tr in active:
            # still text (watermarks, semi-transparent logos) often drops out of detection
            # for a moment: remember it for a few seconds so the blur doesn't flicker
            n = len(tr.keys)
            still = n >= 3 and not _travels(tr.keys, W)
            # a logo seen for 10+ s is surely still there: remember it longer (10 s), short text 4 s
            keep = (10.0 if n * dt >= 10 else 4.0) if still else 2.5 * dt
            (alive if t - tr.last[0] <= keep else done).append(tr)
        active = alive

        if progress and n % 30 == 0 and end:
            progress((t - start) / max(1e-6, end - start), f"Finding Chinese text… {t / 60:.1f}/{end / 60:.1f} min")
    alive_at_end = {id(tr) for tr in active}
    done += active
    scan_end = end or t

    raw = [{"keys": tr.keys, "text": tr.text, "chinese": tr.chinese, "alive": id(tr) in alive_at_end} for tr in done]
    out = build_tracks(raw, mode, W, H, dt, scan_end)
    if progress:
        progress(1.0, f"Found {len(out)} text tracks to blur")
    return out


def build_tracks(raw: list[dict], mode: str, W: float, H: float, dt: float, scan_end: float) -> list[dict]:
    """Turn the scan's raw tracks ({keys, text, chinese, alive}) into blur tracks: sort each into a kind,
    one tight box per subtitle line, a fixed box per logo, and follow moving text."""
    rnd = lambda keys: [[round(float(v), 2) for v in key] for key in keys]  # noqa: E731
    items = []
    for tr in raw:
        k = np.array(tr["keys"])
        moving = _travels(tr["keys"], W)
        items.append((tr, k, moving, _kind(k, tr["text"], moving, tr["chinese"], W, H)))
    # this video's subtitle row: where most subtitle time is. Text off that row (a sign low in the picture)
    # is "other", not a subtitle.
    subs = [(float((k[:, 2] + k[:, 4]).mean() / 2), float(k[-1, 0] - k[0, 0]) + dt, float(np.median(k[:, 4] - k[:, 2])))
            for _, k, _, kind in items if kind == "subtitle"]
    if subs:
        order = sorted(subs)
        half, acc = sum(w for _, w, _ in order) / 2, 0.0
        row = next(cy for cy, w, _ in order if (acc := acc + w) >= half)
        tol = float(np.median([h for _, _, h in subs]))

        def on_row(k: np.ndarray) -> bool:
            h = float(np.median(k[:, 4] - k[:, 2]))
            return abs(float((k[:, 2] + k[:, 4]).mean() / 2) - row) <= tol and 0.6 * tol <= h <= 1.5 * tol

        # text on the subtitle row is subtitle, centred or not (long lines are often found as 2 pieces);
        # text claimed as subtitle but off the row is "other"
        items = [(tr, k, mv, ("subtitle" if on_row(k) and not mv else "other")
                  if kind in ("subtitle", "other") else kind) for tr, k, mv, kind in items]
    out = []
    for tr, k, moving, kind in items:
        h = np.median(k[:, 4] - k[:, 2])
        if mode == "chinese" and not tr["chinese"] and kind != "logo":  # logos may be Latin ("bilibili")
            continue
        if len(k) == 1 and mode == "all" and h < 12:
            continue
        if kind == "subtitle":  # one tight box per line, only while that line is on screen
            for r in _lines(k, dt):
                box = [r[:, 1].min(), r[:, 2].min(), r[:, 3].max(), r[:, 4].max()]
                keys = [[r[0, 0], *box], [r[-1, 0], *box]] if r[-1, 0] > r[0, 0] else [[r[0, 0], *box]]
                # 2 samples either side: a line appears/goes between two samples, never a frame left readable
                out.append({"keys": rnd(keys), "static": True, "text": tr["text"], "dt": 2 * dt, "kind": kind,
                            "pad": round(float(0.06 * (box[3] - box[1]) + 2), 1)})
            continue
        if kind == "logo" and not (moving and _scrolls(k, W, H)):
            # a fixed box where the logo usually is, robust to samples that belonged to other text nearby
            if len(k) < 5:  # few samples: the smallest one (a merge with other text only ever adds area)
                box = list(k[np.argmin((k[:, 3] - k[:, 1]) * (k[:, 4] - k[:, 2])), 1:])
            else:
                box = [np.percentile(k[:, 1], 10), np.percentile(k[:, 2], 10),
                       np.percentile(k[:, 3], 90), np.percentile(k[:, 4], 90)]
            last_t = max(k[-1, 0], scan_end) if tr["alive"] and len(k) >= 3 else k[-1, 0]
            keys = [[k[0, 0], *box], [last_t, *box]] if last_t > k[0, 0] else [[k[0, 0], *box]]
            out.append({"keys": rnd(keys), "static": True, "text": tr["text"], "dt": max(dt, 0.6), "kind": kind,
                        "pad": round(float(0.1 * h + 2), 1)})
            continue
        if not moving:
            box = [k[:, 1].min(), k[:, 2].min(), k[:, 3].max(), k[:, 4].max()]
            last_t = k[-1, 0]
            if tr["alive"] and len(k) >= 3:
                last_t = max(last_t, scan_end)  # still on screen when the video ends
            keys = [[k[0, 0], *box], [last_t, *box]] if last_t > k[0, 0] else [[k[0, 0], *box]]
            ext = max(dt, 0.6)  # still text: a little extra margin before/after
        else:
            keys = k.tolist()
            ext = dt
            tail = _follow_out(k, W, scan_end, tr["alive"])
            if tail:
                keys.append(tail)
        out.append({"keys": rnd(keys), "static": not moving, "text": tr["text"], "dt": ext, "kind": kind})
    start = min((tr["keys"][0][0] for tr in raw), default=0.0)
    return _whole_video_logos(_merge_still(out), start, scan_end)


def _whole_video_logos(tracks: list[dict], start: float, end: float, share: float = 0.4) -> list[dict]:
    """A watermark seen in the same place for much of the video is there all the time (detection just drops
    out now and then): blur it from start to end instead of leaving gaps."""
    span = max(end - start, 1e-6)
    groups: list[list[dict]] = []
    for t in (t for t in tracks if t.get("kind") == "logo" and t["static"]):
        g = next((g for g in groups if _iou(g[0]["keys"][0][1:], t["keys"][0][1:]) > 0.3), None)
        (g.append(t) if g else groups.append([t]))
    out = [t for t in tracks if not (t.get("kind") == "logo" and t["static"])]
    whole, rest = [], []
    for g in groups:
        seen = sum(t["keys"][-1][0] - t["keys"][0][0] + 2 * t["dt"] for t in g)
        if seen >= share * span:
            whole.append([float(v) for v in np.median(np.array([t["keys"][0][1:] for t in g]), axis=0)])
        else:
            rest += g
    for t in rest:  # a piece of the same watermark seen only now and then (a stylised "bilibili"): join it
        b = t["keys"][0][1:]
        for w in whole:
            h = min(b[3] - b[1], w[3] - w[1])
            same_row = min(b[3], w[3]) - max(b[1], w[1]) >= 0.5 * h
            if same_row and max(b[0] - w[2], w[0] - b[2]) <= 1.5 * h:
                w[:] = [min(w[0], b[0]), min(w[1], b[1]), max(w[2], b[2]), max(w[3], b[3])]
                break
        else:
            out.append(t)
    for w in whole:
        box = [round(v, 2) for v in w]
        out.append({"keys": [[start, *box], [end, *box]], "static": True, "text": "watermark", "dt": 0.6,
                    "kind": "logo", "pad": round(0.1 * (box[3] - box[1]) + 2, 1)})
    return out


def _merge_still(tracks: list[dict], max_gap: float = 15.0) -> list[dict]:
    """Join still-text pieces at the same place with short gaps between them (e.g. a logo
    the detector lost for a moment), so the blur doesn't switch off in between."""
    joinable = lambda t: t["static"] and t.get("kind") != "subtitle"  # noqa: E731 - subtitle lines stay apart
    still = sorted((t for t in tracks if joinable(t)), key=lambda t: t["keys"][0][0])
    merged: list[dict] = []
    for tr in still:
        a0, b0 = tr["keys"][0][0], tr["keys"][-1][0]
        box = tr["keys"][0][1:]
        for m in merged:
            ma, mb = m["keys"][0][0], m["keys"][-1][0]
            mbox = m["keys"][0][1:]
            if _iou(box, mbox) > 0.5 and a0 - mb <= max_gap and ma - b0 <= max_gap:
                u = [min(box[0], mbox[0]), min(box[1], mbox[1]), max(box[2], mbox[2]), max(box[3], mbox[3])]
                lo, hi = min(a0, ma), max(b0, mb)
                m["keys"] = [[lo, *u], [hi, *u]]
                m["dt"] = max(m["dt"], tr["dt"])
                break
        else:
            merged.append({**tr, "keys": [list(k) for k in tr["keys"]]})
    return merged + [t for t in tracks if not joinable(t)]


def save_tracks(tracks: list[dict], path: Path) -> None:
    path.write_text(json.dumps(tracks, ensure_ascii=False), encoding="utf-8")


def load_tracks(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def manual_tracks(regions: list[dict], width: int, height: int, duration: float) -> list[dict]:
    """Manual boxes given as fractions of the frame: {x, y, w, h, start?, end?}."""
    out = []
    for r in regions:
        x0, y0 = r["x"] * width, r["y"] * height
        x1, y1 = x0 + r["w"] * width, y0 + r["h"] * height
        a, b = float(r.get("start") or 0), float(r.get("end") or duration)
        out.append({"keys": [[a, x0, y0, x1, y1], [b, x0, y0, x1, y1]], "static": True,
                    "text": "manual", "dt": 0.0, "pad": 0.0, "kind": "manual"})
    return out


class Timeline:
    """Answers 'which boxes to blur at time t' quickly for increasing t."""

    def __init__(self, tracks: list[dict]):
        self.tracks = []
        for tr in tracks:
            keys = sorted(tr["keys"])
            ext = tr.get("dt", 0.33)
            self.tracks.append((keys[0][0] - ext, keys[-1][0] + ext, keys, ext, tr.get("pad")))
        self.tracks.sort(key=lambda x: x[0])
        self._reset()

    def _reset(self):
        self._ptr, self._active, self._last_t = 0, [], float("-inf")

    def __bool__(self):
        return bool(self.tracks)

    def boxes(self, t: float) -> list[tuple[int, int, int, int]]:
        if t < self._last_t:
            self._reset()
        self._last_t = t
        while self._ptr < len(self.tracks) and self.tracks[self._ptr][0] <= t:
            self._active.append(self.tracks[self._ptr])
            self._ptr += 1
        self._active = [tr for tr in self._active if tr[1] >= t]
        return [self._box_at(keys, t, ext, pad) for _, _, keys, ext, pad in self._active]

    @staticmethod
    def _box_at(keys, t, ext, pad):
        ts = [k[0] for k in keys]
        j = bisect.bisect_left(ts, t)
        if len(keys) == 1:
            box = keys[0][1:]
            vel = 0.0
        elif j == 0 or j >= len(keys):
            # before first / after last sample: extrapolate with the edge velocity
            k0, k1 = (keys[0], keys[1]) if j == 0 else (keys[-2], keys[-1])
            d = max(k1[0] - k0[0], 1e-3)
            base = keys[0] if j == 0 else keys[-1]
            dtt = max(-ext, min(ext, t - base[0]))
            v = [(k1[i] - k0[i]) / d for i in range(1, 5)]
            box = [base[i + 1] + v[i] * dtt for i in range(4)]
            vel = float(np.hypot(v[0], v[1]))
        else:
            k0, k1 = keys[j - 1], keys[j]
            f = (t - k0[0]) / max(k1[0] - k0[0], 1e-6)
            box = [k0[i] + (k1[i] - k0[i]) * f for i in range(1, 5)]
            vel = float(np.hypot(k1[1] - k0[1], k1[2] - k0[2]) / max(k1[0] - k0[0], 1e-6))
        h = box[3] - box[1]
        p = (h * 0.12 + 3) if pad is None else pad  # close around the text; the detector's box already has a margin
        p_motion = vel * ext * 0.3 if pad is None else 0
        return (int(box[0] - p - p_motion), int(box[1] - p), int(box[2] + p + p_motion), int(box[3] + p))


def apply(frame: np.ndarray, boxes, style: str = "blur") -> None:
    import cv2

    H, W = frame.shape[:2]
    for x0, y0, x1, y1 in boxes:
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
        w, h = x1 - x0, y1 - y0
        if w < 2 or h < 2:
            continue
        roi = frame[y0:y1, x0:x1]
        if style == "box":
            frame[y0:y1, x0:x1] = (roi * 0.15).astype(np.uint8)
        elif style == "pixelate":
            s = cv2.resize(roi, (max(1, w // 14), max(1, h // 14)), interpolation=cv2.INTER_AREA)
            frame[y0:y1, x0:x1] = cv2.resize(s, (w, h), interpolation=cv2.INTER_NEAREST)
        else:
            s = cv2.resize(roi, (max(1, w // 8), max(1, h // 8)), interpolation=cv2.INTER_AREA)
            s = cv2.GaussianBlur(s, (0, 0), sigmaX=1.6)
            frame[y0:y1, x0:x1] = cv2.resize(s, (w, h), interpolation=cv2.INTER_CUBIC)
