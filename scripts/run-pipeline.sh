#!/usr/bin/env bash
#
# run-pipeline.sh — the M1's local feed updater, called by the launchd timer
# (see setup-m1-local-pipeline.sh). Translates via local Ollama and pushes
# feed.json *outbound* to GitHub. Nothing ever reaches into the Mac.
#
# Run manually any time to test:  ./scripts/run-pipeline.sh
#
set -euo pipefail

# Resolve the repo root from this script's location, regardless of cwd (launchd
# starts jobs with an unpredictable working directory).
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

BRANCH="${SENAL_BRANCH:-main}"   # the branch GitHub Pages serves from

# launchd jobs get a bare environment — set a PATH that finds brew, git, python,
# ollama on Apple Silicon (and Intel, just in case).
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

# Translate locally by default; optional overrides/keys (e.g. a Claude fallback
# key) can live in ~/.senal.env — kept out of the repo.
export TRANSLATE_BACKEND="${TRANSLATE_BACKEND:-ollama}"
if [[ -f "$HOME/.senal.env" ]]; then
  set -a; . "$HOME/.senal.env"; set +a
fi

echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') ====="

# Confirm Ollama is reachable; if not, the script still runs but will leave items
# in English (or use a Claude fallback key if one is configured).
if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo "WARNING: Ollama not reachable on localhost:11434 — is 'brew services' running?"
fi

# Stay in sync with GitHub before regenerating, so the push is a fast-forward.
git pull --rebase --autostash origin "$BRANCH" || echo "WARNING: git pull failed; continuing"

PY="$REPO/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)"
"$PY" fetch_and_translate.py

if git diff --quiet -- feed.json; then
  echo "No changes to feed.json."
else
  git add feed.json
  git commit -m "Update feed.json ($(date -u +%Y-%m-%d))"
  # Retry the push a few times in case the network blips.
  for attempt in 1 2 3 4; do
    if git push origin "$BRANCH"; then
      echo "Pushed."
      break
    fi
    echo "push failed (attempt $attempt) — retrying in $((attempt * 2))s"
    sleep $((attempt * 2))
  done
fi
