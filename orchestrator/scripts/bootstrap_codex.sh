#!/usr/bin/env bash
set -eou pipefail

CODEX_REPO_DIR="${1:-../codex}"

if [ ! -d "$CODEX_REPO_DIR" ]; then
    # Clone the Codex repository if it doesn't exist
    git clone https://github.com/openai/codex.git "$CODEX_REPO_DIR"
else
    git -C "$CODEX_REPO_DIR" pull --ff-only
fi

poetry install
poetry run python -m pip install -e "$CODEX_REPO_DIR/sdk/python"