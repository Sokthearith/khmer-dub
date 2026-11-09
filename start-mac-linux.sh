#!/usr/bin/env bash
# Khmer Dub - run ./start-mac-linux.sh (or double-click start-mac.command on a Mac).
# First start downloads 2-4 GB (Python, AI models).
set -e
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv (Python manager)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

EXTRA=cpu
if command -v nvidia-smi >/dev/null 2>&1; then EXTRA=gpu; fi

echo
echo "Starting Khmer Dub ($EXTRA mode). The app opens in your browser when ready."
echo "Keep this window open while you use the app."
echo
exec uv run --extra "$EXTRA" khmerdub ui "$@"
