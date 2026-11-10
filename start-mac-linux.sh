#!/usr/bin/env bash
# Khmer Dub - run ./start-mac-linux.sh (or double-click start-mac.command on a Mac).
# First start downloads 2-4 GB (Python, AI models) and adds a "Khmer Dub" app to your
# Applications / app menu.
set -e
cd "$(dirname "$0")"
# shortcuts start without your terminal's PATH: add the usual places uv lives
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv (Python manager)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

EXTRA=cpu
if command -v nvidia-smi >/dev/null 2>&1; then EXTRA=gpu; fi

# install a downloaded update (if any) before the app opens
uv run --extra "$EXTRA" --extra offline khmerdub update --apply || true

echo
echo "Starting Khmer Dub ($EXTRA mode). It opens in its own window when ready."
echo "Keep this window open while you use the app."
echo
exec uv run --extra "$EXTRA" --extra offline khmerdub app "$@"
