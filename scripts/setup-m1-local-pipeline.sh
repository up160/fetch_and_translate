#!/usr/bin/env bash
#
# setup-m1-local-pipeline.sh — make the M1 the self-contained, outbound-only feed
# updater. Translation runs on local Ollama; feed.json is pushed to GitHub on a
# schedule by a launchd timer. Nothing listens for inbound connections.
#
# Run once on the Mac, from the repo root:
#   ./scripts/setup-m1-local-pipeline.sh
#
# Prereqs: Ollama set up (run ./scripts/setup-m1-ollama.sh first) and `git push`
# already working for this clone (HTTPS-with-keychain or an SSH remote).
#
set -euo pipefail

note() { printf '\n==> %s\n' "$1"; }

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Run this on the macOS M1. Detected $(uname -s)." >&2
  exit 1
fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
BRANCH="${SENAL_BRANCH:-main}"
LABEL="com.senal.feed"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

# ── 1. Python venv + deps ────────────────────────────────────────────────────
note "1/4 Create venv and install dependencies"
if [[ ! -x "$REPO/.venv/bin/python" ]]; then
  python3 -m venv "$REPO/.venv"
fi
"$REPO/.venv/bin/python" -m pip install --quiet --upgrade pip
"$REPO/.venv/bin/python" -m pip install --quiet -r requirements.txt
echo "    venv ready: $REPO/.venv"

# ── 2. Smoke-run the pipeline once ───────────────────────────────────────────
note "2/4 Test run (translates locally and pushes if feed.json changed)"
chmod +x "$REPO/scripts/run-pipeline.sh"
SENAL_BRANCH="$BRANCH" "$REPO/scripts/run-pipeline.sh" || {
  echo "    Test run failed — fix the error above before installing the timer." >&2
  exit 1
}

# ── 3. Install the launchd timer ─────────────────────────────────────────────
# Runs four times a day in *local* time. launchd also fires a missed slot on the
# next wake, so a sleeping/closed Mac still catches up.
note "3/4 Install launchd timer ($PLIST)"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${REPO}/scripts/run-pipeline.sh</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>SENAL_BRANCH</key>
    <string>${BRANCH}</string>
  </dict>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>22</integer><key>Minute</key><integer>30</integer></dict>
  </array>
  <key>StandardOutPath</key>
  <string>${REPO}/pipeline.log</string>
  <key>StandardErrorPath</key>
  <string>${REPO}/pipeline.log</string>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
EOF

# Reload cleanly if it was already installed.
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

# ── 4. Done ──────────────────────────────────────────────────────────────────
note "4/4 Installed"
cat <<EOF

  The M1 will refresh the feed at 07:30 / 12:30 / 17:30 / 22:30 (local time)
  and push to '${BRANCH}'. Everything is outbound — nothing listens for inbound.

  Logs:        tail -f "${REPO}/pipeline.log"
  Run now:     launchctl start ${LABEL}
  Check timer: launchctl list | grep ${LABEL}
  Remove:      launchctl unload "${PLIST}" && rm "${PLIST}"

  Tips:
    - Disable system sleep so the slots fire:  sudo pmset -a sleep 0
    - Optional Claude fallback key:  echo 'ANTHROPIC_API_KEY=sk-ant-...' > ~/.senal.env
EOF
