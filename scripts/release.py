"""Publish a new version of Khmer Dub that everyone's app will offer as an update.

    uv run python scripts/release.py 0.3.0 "Faster blur scan. New: voice speed per line."

It sets the version, commits, tags vX.Y.Z, pushes, and creates the GitHub Release
(needs the GitHub CLI `gh`, logged in). The notes are what people see under "What's new";
the first line also appears in the app's update bar, so make it a short summary.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*cmd: str) -> str:
    print("$", " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def main() -> None:
    if len(sys.argv) < 3 or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
        sys.exit(__doc__)
    version, notes = sys.argv[1], sys.argv[2]
    if run("git", "status", "--porcelain"):
        sys.exit("Commit or stash your changes first: a release must be exactly what is on GitHub.")
    if run("git", "rev-parse", "--abbrev-ref", "HEAD") != "main":
        sys.exit("Release from the main branch.")

    py = ROOT / "pyproject.toml"
    py.write_text(re.sub(r'(?m)^version = "[^"]+"', f'version = "{version}"', py.read_text(), count=1))
    init = ROOT / "src" / "khmerdub" / "__init__.py"
    init.write_text(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', init.read_text()))
    run("uv", "lock")

    run("git", "add", "pyproject.toml", "uv.lock", "src/khmerdub/__init__.py")
    run("git", "commit", "-m", f"Release {version}")
    run("git", "tag", f"v{version}")
    run("git", "push", "origin", "main", f"v{version}")
    url = run("gh", "release", "create", f"v{version}", "--title", f"Khmer Dub {version}", "--notes", notes)
    print(f"Released {version}: {url}")


if __name__ == "__main__":
    main()
