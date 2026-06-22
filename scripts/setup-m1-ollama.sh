#!/usr/bin/env bash
#
# setup-m1-ollama.sh — provision a macOS (M1/16GB) box as the translation
# backend for fetch_and_translate. Idempotent: safe to re-run.
#
# What it does:
#   1. Installs Ollama (via Homebrew) if missing.
#   2. Configures the Ollama service to listen on the tailnet, not just
#      localhost, and keeps it running across reboots.
#   3. Pulls the translation model.
#   4. Stops the Mac sleeping through the CI cron slots (needs sudo).
#   5. Runs a Spanish-quality smoke test against the running model.
#   6. Prints the exact OLLAMA_HOST value to paste into the GitHub secret.
#
# Usage:
#   ./scripts/setup-m1-ollama.sh
#   OLLAMA_MODEL=qwen2.5:14b-instruct ./scripts/setup-m1-ollama.sh
#   SKIP_SLEEP=1 ./scripts/setup-m1-ollama.sh        # don't touch pmset
#
set -euo pipefail

MODEL="${OLLAMA_MODEL:-qwen2.5:7b-instruct}"
PORT="${OLLAMA_PORT:-11434}"

note() { printf '\n==> %s\n' "$1"; }

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script targets the macOS M1. Detected $(uname -s) — run it on the Mac." >&2
  exit 1
fi

# ── 1. Install Ollama ────────────────────────────────────────────────────────
note "1/6 Install Ollama"
if command -v ollama >/dev/null 2>&1; then
  echo "    already installed: $(ollama --version 2>/dev/null | head -1)"
elif command -v brew >/dev/null 2>&1; then
  brew install ollama
else
  echo "    Homebrew not found. Install it from https://brew.sh and re-run," >&2
  echo "    or download Ollama directly from https://ollama.com/download" >&2
  exit 1
fi

# ── 2. Listen on the tailnet + run as a service ──────────────────────────────
note "2/6 Bind Ollama to all interfaces so the tailnet can reach it"
# launchctl setenv makes the brew-services (launchd) Ollama pick up the host.
launchctl setenv OLLAMA_HOST "0.0.0.0:${PORT}"
brew services restart ollama >/dev/null 2>&1 || brew services start ollama
# Give the server a moment to come up before we pull / test.
for _ in $(seq 1 15); do
  curl -sf "http://localhost:${PORT}/api/tags" >/dev/null 2>&1 && break
  sleep 1
done

# ── 3. Pull the model ────────────────────────────────────────────────────────
note "3/6 Pull model: ${MODEL}"
ollama pull "${MODEL}"

# ── 4. Keep the Mac awake for the cron slots ─────────────────────────────────
note "4/6 Prevent sleep (00:23 / 06:23 / 12:23 / 18:23 UTC runs)"
if [[ "${SKIP_SLEEP:-0}" == "1" ]]; then
  echo "    skipped (SKIP_SLEEP=1)"
elif sudo -n true 2>/dev/null || sudo true; then
  sudo pmset -a sleep 0 && echo "    system sleep disabled"
else
  echo "    couldn't run pmset; if the box sleeps, run: sudo pmset -a sleep 0"
fi

# ── 5. Spanish-quality smoke test ────────────────────────────────────────────
note "5/6 Smoke test — translating two sample headlines"
read -r -d '' PROMPT <<'EOF' || true
You are a professional news translator producing Spanish (Spain) copy for a daily reader.
Translate each item from English to Spanish. Write natural, fluent, idiomatic journalistic
Spanish. Keep proper nouns (teams, players, places, brands) untranslated; use Spanish
exonyms for countries. Preserve numbers, scores and dates exactly.
Return ONLY a JSON array; each object has exactly: id, title_es, summary_es.
Items to translate:
[{"id":"a1","title":"Salah scores to help Egypt to first World Cup win","summary":"Mohamed Salah scores one goal and creates another as Egypt come from behind to beat Australia 2-1."},
 {"id":"a2","title":"Mexico 1-0 South Korea","summary":"Group Stage. Played on 2026-06-19."}]
EOF

REQ=$(MODEL="$MODEL" PROMPT="$PROMPT" python3 - <<'PY'
import json, os
print(json.dumps({
    "model": os.environ["MODEL"],
    "messages": [{"role": "user", "content": os.environ["PROMPT"]}],
    "stream": False,
    "format": "json",
    "options": {"temperature": 0.2},
}))
PY
)

if RESP=$(curl -sf "http://localhost:${PORT}/api/chat" \
            -H 'Content-Type: application/json' -d "$REQ"); then
  RESP="$RESP" python3 <<'PY'
import json, os
data = json.loads(os.environ["RESP"])
content = data.get("message", {}).get("content", "")
try:
    items = json.loads(content)
    if isinstance(items, dict):
        items = next((v for v in items.values() if isinstance(v, list)), [items])
    for it in items:
        print("  - " + str(it.get("title_es", "?")))
        summary = it.get("summary_es")
        if summary:
            print("    " + str(summary))
    print("\n  OK: model returns parseable Spanish.")
except Exception as e:
    print("  Could not parse model output as JSON:", e)
    print("  Raw:", content[:400])
PY
else
  echo "    Could not reach Ollama at localhost:${PORT} — check 'brew services list'."
fi

# ── 6. Print the OLLAMA_HOST value for the GitHub secret ─────────────────────
note "6/6 Tailscale address for the GitHub OLLAMA_HOST secret"
if command -v tailscale >/dev/null 2>&1; then
  tailscale up >/dev/null 2>&1 || true
  NAME=$(tailscale status --json 2>/dev/null \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || true)
  IP=$(tailscale ip -4 2>/dev/null | head -1 || true)
  HOST="${NAME:-$IP}"
  if [[ -n "$HOST" ]]; then
    echo "    Set repo secret OLLAMA_HOST to:"
    echo "        http://${HOST}:${PORT}"
  else
    echo "    Tailscale is installed but not logged in. Run 'tailscale up' and re-run."
  fi
else
  echo "    Tailscale not installed. Install and re-run:"
  echo "        brew install --cask tailscale && open -a Tailscale"
fi

echo
echo "Next: add OLLAMA_HOST (above) and TS_AUTHKEY (a reusable+ephemeral key from"
echo "https://login.tailscale.com/admin/settings/keys) as GitHub Actions secrets,"
echo "then trigger Actions → Update feed → Run workflow. See README → 'Wiring the"
echo "M1 into the daily CI run'."
