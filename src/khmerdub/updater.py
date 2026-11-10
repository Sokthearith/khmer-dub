"""Built-in updater.

How it works
1. check()   asks GitHub for the latest Release of Sokthearith/khmer-dub (at most every 6 hours).
2. stage()   downloads that release and unpacks it into .update/ inside the app folder.
3. apply_pending() runs at the next start (from the start scripts, before the app opens) and copies the
   new program files over the old ones.

Never touched: projects/ (your work), .venv/ (installed libraries), the AI models (stored elsewhere),
and any git folder (a developer's copy must be updated with `git pull`, never overwritten).

Windows can't replace a .bat file while it runs, so a changed start-windows.bat is written as
start-windows.bat.new and the start script swaps it in on the following start.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from . import __version__

REPO = "Sokthearith/khmer-dub"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_EVERY = 6 * 3600  # seconds
KEEP = {"projects", ".venv", ".git", ".update", "__pycache__", ".claude"}


@dataclass
class Release:
    version: str
    tag: str
    notes: str
    zip_url: str
    page_url: str


def root() -> Path:
    return Path(__file__).resolve().parents[2]


def update_dir() -> Path:
    d = root() / ".update"
    d.mkdir(exist_ok=True)
    return d


def is_git_checkout() -> bool:
    return (root() / ".git").exists()


def parse_version(v: str) -> tuple[int, int, int]:
    nums = [int(n) for n in re.findall(r"\d+", v)[:3]]
    return tuple(nums + [0] * (3 - len(nums)))  # type: ignore[return-value]


def current_version() -> str:
    return __version__


# ------------------------------------------------------------------- check ---
def latest_release(timeout: float = 4.0, use_cache: bool = True) -> Release | None:
    """The newest published release, or None (no internet, no releases yet, GitHub busy)."""
    cache = update_dir() / "latest.json"
    data = None
    if use_cache and cache.exists() and time.time() - cache.stat().st_mtime < CHECK_EVERY:
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
        except Exception:
            data = None
    if data is None:
        try:
            import requests

            r = requests.get(LATEST_API, timeout=timeout, headers={
                "Accept": "application/vnd.github+json", "User-Agent": "khmerdub-updater"})
            if r.status_code != 200:
                return None
            j = r.json()
            data = {"version": j["tag_name"].lstrip("vV"), "tag": j["tag_name"], "notes": j.get("body") or "",
                    "zip_url": j["zipball_url"], "page_url": j["html_url"]}
            cache.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            return None
    return Release(**data)


def check(use_cache: bool = True) -> Release | None:
    """The latest release if it is newer than this copy, else None."""
    rel = latest_release(use_cache=use_cache)
    if rel and parse_version(rel.version) > parse_version(current_version()):
        return rel
    return None


# ------------------------------------------------------------------- stage ---
def stage(rel: Release, progress: Callable[[float, str], None] | None = None) -> Path:
    """Download and unpack a release into .update/; it is applied at the next start."""
    if is_git_checkout():
        raise RuntimeError("This copy is a git folder. Update it with `git pull` instead.")
    import requests

    d = update_dir()
    zpath = d / f"{rel.tag}.zip"
    with requests.get(rel.zip_url, stream=True, timeout=30, headers={"User-Agent": "khmerdub-updater"}) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        got = 0
        with open(zpath, "wb") as f:
            for chunk in r.iter_content(256 * 1024):
                f.write(chunk)
                got += len(chunk)
                if progress:
                    progress(got / total if total else 0.5, f"Downloading Khmer Dub {rel.version}")

    target = d / f"staged-{rel.tag}"
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    base = target.resolve()
    with zipfile.ZipFile(zpath) as zf:
        for info in zf.infolist():
            parts = Path(info.filename).parts[1:]  # drop GitHub's top folder "owner-repo-sha/"
            if not parts:
                continue
            dest = (target.joinpath(*parts)).resolve()
            if base not in dest.parents and dest != base:  # never write outside the staging folder
                raise RuntimeError(f"Unsafe path in update: {info.filename}")
            if info.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            mode = (info.external_attr >> 16) & 0o777
            if mode:
                dest.chmod(mode)
    zpath.unlink(missing_ok=True)
    if not ((target / "pyproject.toml").exists() and (target / "src" / "khmerdub" / "__init__.py").exists()):
        shutil.rmtree(target, ignore_errors=True)
        raise RuntimeError("The downloaded update looks incomplete. Try again later.")
    (d / "pending.json").write_text(json.dumps({**asdict(rel), "path": str(target)}), encoding="utf-8")
    if progress:
        progress(1.0, "Update ready")
    return target


def pending() -> dict | None:
    p = update_dir() / "pending.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# ------------------------------------------------------------------- apply ---
def _replace_file(src: Path, target: Path) -> None:
    data = src.read_bytes()
    if target.exists() and target.read_bytes() == data:
        return
    if os.name == "nt" and target.suffix.lower() == ".bat":
        # the start script is running right now: the next start swaps this in
        target.with_name(target.name + ".new").write_bytes(data)
        return
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(data)
    shutil.copymode(src, tmp)
    os.replace(tmp, target)  # new file, so a shell still reading the old script is not disturbed


def apply_pending(log: Callable[[str], None] = print) -> str | None:
    """Install a downloaded update. Returns the new version, or None when there was nothing to do."""
    p = pending()
    if not p:
        return None
    d = update_dir()
    staged = Path(p.get("path", ""))

    def clear() -> None:
        (d / "pending.json").unlink(missing_ok=True)
        shutil.rmtree(staged, ignore_errors=True)

    if is_git_checkout():
        log("Not updating: this copy is a git folder (use git pull).")
        clear()
        return None
    if not (staged / "src" / "khmerdub" / "__init__.py").exists():
        log("The downloaded update is missing; it will be downloaded again.")
        clear()
        return None

    dst = root()
    for item in sorted(staged.iterdir()):
        if item.name in KEEP:
            continue
        target = dst / item.name
        if item.is_dir():
            fresh, old = dst / (item.name + ".updating"), dst / (item.name + ".old")
            shutil.rmtree(fresh, ignore_errors=True)
            shutil.rmtree(old, ignore_errors=True)
            shutil.copytree(item, fresh)
            if target.exists():
                target.rename(old)
            fresh.rename(target)
            shutil.rmtree(old, ignore_errors=True)
        else:
            _replace_file(item, target)
    (d / "updated.txt").write_text(p["version"], encoding="utf-8")
    (d / "latest.json").unlink(missing_ok=True)
    clear()
    log(f"Khmer Dub updated to {p['version']}.")
    return p["version"]


def just_updated() -> str | None:
    """The version installed at this start (shown once in the app), else None."""
    f = update_dir() / "updated.txt"
    if not f.exists():
        return None
    v = f.read_text(encoding="utf-8").strip()
    f.unlink(missing_ok=True)
    return v or None
