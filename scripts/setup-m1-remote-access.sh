#!/usr/bin/env bash
#
# setup-m1-remote-access.sh — let *you* (from your phone) and *Claude* both work
# on the M1, over Tailscale. Pairs with setup-m1-ollama.sh.
#
#   - Tailscale SSH: shell in from anywhere with no SSH keys to manage.
#   - tmux: a session that survives a dropped mobile connection.
#   - (optional) Claude Code CLI: so Claude runs ON the M1 with full local access.
#
# This cloud Claude session cannot reach your home M1 — "Claude accesses the M1"
# means a Claude Code process running on the Mac, which you reach by SSHing in.
#
# Usage:
#   ./scripts/setup-m1-remote-access.sh                    # SSH + tmux
#   INSTALL_CLAUDE=1 ./scripts/setup-m1-remote-access.sh   # also install Claude Code
#
set -euo pipefail

note() { printf '\n==> %s\n' "$1"; }

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Run this on the macOS M1. Detected $(uname -s)." >&2
  exit 1
fi

if ! command -v tailscale >/dev/null 2>&1; then
  echo "Tailscale isn't installed. Install it, sign in, then re-run:" >&2
  echo "    brew install --cask tailscale && open -a Tailscale" >&2
  exit 1
fi

# ── 1. Tailscale SSH ─────────────────────────────────────────────────────────
# Authenticates incoming SSH via your tailnet identity + ACLs — no authorized_keys
# to manage. Nothing is exposed to the public internet; reachable only on the tailnet.
note "1/4 Enable Tailscale SSH"
sudo tailscale up --ssh

# ── 2. tmux for durable phone sessions ───────────────────────────────────────
note "2/4 Install tmux (so a session survives a flaky phone connection)"
if command -v tmux >/dev/null 2>&1; then
  echo "    already installed"
elif command -v brew >/dev/null 2>&1; then
  brew install tmux
else
  echo "    Homebrew missing; install tmux manually for resilient sessions."
fi

# ── 3. Claude Code on the M1 (optional) ──────────────────────────────────────
note "3/4 Claude Code CLI"
if [[ "${INSTALL_CLAUDE:-0}" == "1" ]]; then
  if ! command -v node >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then brew install node; else
      echo "    Node not found and no Homebrew; install Node 18+ then: npm i -g @anthropic-ai/claude-code" >&2
    fi
  fi
  if command -v npm >/dev/null 2>&1; then
    npm install -g @anthropic-ai/claude-code \
      && echo "    installed. Run 'claude' once to log in (browser or API key)." \
      || echo "    npm install failed — see https://docs.claude.com/en/docs/claude-code"
  fi
else
  echo "    skipped (set INSTALL_CLAUDE=1 to install)."
  echo "    Manual: brew install node && npm install -g @anthropic-ai/claude-code"
fi

# ── 4. Your phone connection details ─────────────────────────────────────────
note "4/4 Connect from your phone"
NAME=$(tailscale status --json 2>/dev/null \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || true)
IP=$(tailscale ip -4 2>/dev/null | head -1 || true)
HOST="${NAME:-${IP:-<tailnet-address>}}"
USER_NAME="$(whoami)"

cat <<EOF

  On the phone: install the Tailscale app (same account) + an SSH client
  (iOS: Termius/Blink · Android: Termius or Termux). Then:

      ssh ${USER_NAME}@${HOST}

  Start a durable session (survives the connection dropping):

      tmux new -s work          # later, reconnect with:  tmux attach -t work

  Drive Claude on the M1:

      cd ~/path/to/fetch_and_translate && claude

EOF
