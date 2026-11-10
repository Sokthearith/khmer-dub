"""Run Khmer Dub like a desktop app: its own window, and shortcuts on the desktop / Start menu / Applications.

Window, in order of preference:
  Windows, macOS : a native window (pywebview: Edge WebView2 / Safari WebKit), then a Chrome/Edge app window
  Linux          : a Chrome/Chromium/Edge app window (plays H.264 video), then pywebview if installed
  anywhere       : the normal browser as a last resort
Closing the window stops the app.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

ASSETS = Path(__file__).parent / "assets"
ICON_PNG, ICON_ICO, ICON_ICNS = ASSETS / "icon.png", ASSETS / "icon.ico", ASSETS / "icon.icns"
TITLE = "Khmer Dub"
SYSTEM = platform.system()  # Windows | Darwin | Linux


# ------------------------------------------------------------------ windows ---
def _data_dir() -> Path:
    if SYSTEM == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif SYSTEM == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    d = base / "khmerdub"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _chromium_commands() -> list[tuple[list[str], str | None]]:
    """Installed Chromium-family browsers as (command, flatpak id or None)."""
    found: list[tuple[list[str], str | None]] = []
    if SYSTEM == "Windows":
        rels = [r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe",
                r"BraveSoftware\Brave-Browser\Application\brave.exe"]
        for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            base = os.environ.get(env)
            for rel in rels if base else []:
                exe = Path(base) / rel
                if exe.exists():
                    found.append(([str(exe)], None))
    elif SYSTEM == "Darwin":
        for app in ("Google Chrome", "Microsoft Edge", "Chromium", "Brave Browser"):
            exe = Path("/Applications") / f"{app}.app" / "Contents" / "MacOS" / app
            if exe.exists():
                found.append(([str(exe)], None))
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
                     "microsoft-edge-stable", "brave-browser"):
            exe = shutil.which(name)
            if exe:
                found.append(([exe], None))
        if shutil.which("flatpak"):
            for app_id in ("com.google.Chrome", "org.chromium.Chromium", "com.microsoft.Edge", "com.brave.Browser"):
                if subprocess.run(["flatpak", "info", app_id], capture_output=True).returncode == 0:
                    found.append((["flatpak", "run", app_id], app_id))
    return found


def _chromium_window(url: str, width: int, height: int, log: Callable[[str], None]) -> str | None:
    """Open url in a Chrome/Edge 'app' window (no tabs, no address bar) and wait until it is closed."""
    for cmd, flatpak_id in _chromium_commands():
        # a profile of its own makes a separate browser process, so we can tell when the window closes
        if flatpak_id:  # a flatpak browser can only write inside its own folder
            profile = Path.home() / ".var" / "app" / flatpak_id / "data" / "khmerdub-window"
        else:
            profile = _data_dir() / "window-profile"
        profile.mkdir(parents=True, exist_ok=True)
        args = cmd + [f"--app={url}", f"--user-data-dir={profile}", f"--window-size={width},{height}",
                      "--no-first-run", "--no-default-browser-check", "--class=KhmerDub"]
        try:
            proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            continue
        started = time.time()
        proc.wait()
        if time.time() - started < 4:
            if proc.returncode:  # this browser could not open the window (crashed, bad profile): try the next way
                continue
            # the browser handed the window to an already running copy: we can't see it close
            log("Khmer Dub is open in its window. Close this black window to stop the app.")
            return "handed-off"
        return "chromium"
    return None


def _native_window(url: str, width: int, height: int, log: Callable[[str], None]) -> str | None:
    try:
        import webview
    except Exception:
        return None
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True  # the Downloads list must save files
        try:
            screen = webview.screens[0]
            width, height = min(width, int(screen.width * 0.92)), min(height, int(screen.height * 0.88))
        except Exception:
            pass
        webview.create_window(TITLE, url, width=width, height=height, min_size=(880, 600))
        webview.start(icon=str(ICON_PNG))
        return "native"
    except Exception as e:  # missing WebView2 / GUI toolkit: try the next way
        log(f"Native window not available ({e}); trying another way.")
        return None


def open_window(url: str, width: int = 1440, height: int = 900, log: Callable[[str], None] = print) -> str:
    """Show the app in its own window and return when the window is closed.

    Returns how it was shown: native | chromium | handed-off | browser.
    For handed-off and browser the caller keeps the server running until the console is closed.
    """
    order = [_chromium_window, _native_window] if SYSTEM == "Linux" else [_native_window, _chromium_window]
    for way in order:
        how = way(url, width, height, log)
        if how:
            return how
    import webbrowser

    webbrowser.open(url)
    log(f"Opened Khmer Dub in your browser: {url}  (close this black window to stop the app)")
    return "browser"


# ---------------------------------------------------------------- shortcuts ---
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _launcher(root: Path) -> Path:
    return root / ("start-windows.bat" if SYSTEM == "Windows" else "start-mac-linux.sh")


def _windows_shortcuts(root: Path) -> list[str]:
    def q(p) -> str:  # single-quoted PowerShell string
        return "'" + str(p).replace("'", "''") + "'"

    script = f"""
$w = New-Object -ComObject WScript.Shell
$made = @()
foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {{
  $path = Join-Path $dir 'Khmer Dub.lnk'
  $s = $w.CreateShortcut($path)
  $s.TargetPath = {q(_launcher(root))}
  $s.WorkingDirectory = {q(root)}
  $s.IconLocation = {q(ICON_ICO)}
  $s.WindowStyle = 7
  $s.Description = 'Khmer Dub: Chinese video to Khmer dub'
  $s.Save()
  $made += $path
}}
$made -join "`n"
"""
    out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[-500:])
    return [line for line in out.stdout.splitlines() if line.strip()]


def _mac_app(root: Path) -> list[str]:
    app = Path.home() / "Applications" / f"{TITLE}.app"
    macos, res = app / "Contents" / "MacOS", app / "Contents" / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    res.mkdir(parents=True, exist_ok=True)
    exe = macos / "khmerdub"
    launcher = str(_launcher(root)).replace('"', '\\"')
    exe.write_text(f'#!/bin/bash\ncd "{root}" && exec "{launcher}"\n')
    exe.chmod(0o755)
    shutil.copy(ICON_ICNS, res / "icon.icns")
    (app / "Contents" / "Info.plist").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>{TITLE}</string>
  <key>CFBundleDisplayName</key><string>{TITLE}</string>
  <key>CFBundleIdentifier</key><string>io.github.sokthearith.khmerdub</string>
  <key>CFBundleExecutable</key><string>khmerdub</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
</dict></plist>
""")
    return [str(app)]


def _linux_desktop_entry(root: Path) -> list[str]:
    def esc(p) -> str:  # quoted Exec argument per the desktop entry spec
        return '"' + str(p).replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$") + '"'

    entry = f"""[Desktop Entry]
Type=Application
Name={TITLE}
Comment=Chinese video to Khmer dub, subtitles and text blur
Exec={esc(_launcher(root))}
Path={root}
Icon={ICON_PNG}
Terminal=false
Categories=AudioVideo;Video;
StartupWMClass=KhmerDub
"""
    made = []
    apps = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    for path in [apps / "khmer-dub.desktop"]:
        path.write_text(entry)
        path.chmod(0o755)
        made.append(str(path))
    desktop = Path.home() / "Desktop"
    if desktop.is_dir():
        path = desktop / "khmer-dub.desktop"
        path.write_text(entry)
        path.chmod(0o755)
        if shutil.which("gio"):  # GNOME: allow launching without the "untrusted" prompt
            subprocess.run(["gio", "set", str(path), "metadata::trusted", "true"], capture_output=True)
        made.append(str(path))
    return made


def make_shortcuts(log: Callable[[str], None] = print) -> list[str]:
    """Create 'Khmer Dub' shortcuts with the app icon. Safe to run again (it overwrites them)."""
    root = repo_root()
    if not _launcher(root).exists():
        raise RuntimeError(f"Launcher not found next to the app ({_launcher(root)}).")
    if SYSTEM == "Windows":
        made = _windows_shortcuts(root)
    elif SYSTEM == "Darwin":
        made = _mac_app(root)
    else:
        made = _linux_desktop_entry(root)
    (_data_dir() / "shortcuts.txt").write_text(str(root))
    for m in made:
        log(f"Shortcut: {m}")
    return made


def ensure_shortcuts(log: Callable[[str], None] = print) -> None:
    """Make the shortcuts once (and again if the app folder moved). Never fails the start."""
    marker = _data_dir() / "shortcuts.txt"
    try:
        if marker.exists() and marker.read_text().strip() == str(repo_root()):
            return
        make_shortcuts(log)
    except Exception as e:
        log(f"Could not create shortcuts ({e}). You can still start Khmer Dub with the start script.")
