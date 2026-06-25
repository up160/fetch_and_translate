# SEÑAL // Feed Diario

Daily RSS reader that fetches English-language news and translates it to Spanish.
Translation runs through a **local Ollama model** or the **Claude API** (or both,
with automatic fallback). Hosted on GitHub Pages.

## Structure

```
├── fetch_and_translate.py   # Daily fetch + translate script
├── requirements.txt
├── feeds.json               # Feed sources + per-feed item cap
├── feed.json                # Generated output (committed by CI)
├── index.html               # Static site
└── .github/
    └── workflows/
        └── update-feed.yml  # Scheduled GitHub Action
```

## Setup

### 1. Create GitHub repo & enable Pages

- Push this directory to a new GitHub repo
- Go to **Settings → Pages → Source**: set to `Deploy from branch`, branch `main`, folder `/root`
- Your site will be at `https://<your-username>.github.io/<repo-name>/`

### 2. Add your translation backend secret(s)

- Go to **Settings → Secrets and variables → Actions**
- Add a secret named **`ANTHROPIC_SECRET_KEY`** with your key from console.anthropic.com
  (the workflow maps it to the `ANTHROPIC_API_KEY` env var the script reads).
- *(Optional)* add **`FOOTBALL_API_KEY`** (from football-data.org) to enable the
  live World Cup scores section.

### 3. Generate initial feed.json

Run locally first to verify everything works:

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python fetch_and_translate.py
```

Commit the resulting `feed.json`, then push. The site will render immediately.

### 4. Let it run automatically

The primary updater is the **home M1**, running the whole pipeline locally and
pushing `feed.json` *outbound* to GitHub on a schedule — nothing reaches into the
Mac. See [Run the pipeline on the M1](#run-the-pipeline-on-the-m1-outbound-only).

The GitHub Action (`update-feed.yml`) is a **manual break-glass fallback** only
(no schedule, to avoid double-commits). If the M1 is down, trigger it from the
**Actions** tab → **Run workflow** to refresh via the Claude API.

## Translation backends

Translation is backend-agnostic and selected via environment variables. Whichever
backend is primary, the other (if configured) is used as an automatic fallback, so
the build never hard-fails — at worst an item is left in its original English.

| Env var             | Default                  | Purpose |
|---------------------|--------------------------|---------|
| `TRANSLATE_BACKEND` | `auto`                   | `auto` \| `ollama` \| `claude`. `auto` uses Ollama if `OLLAMA_HOST` is set, otherwise Claude. |
| `OLLAMA_HOST`       | `http://localhost:11434` | Ollama server URL (used when backend is `ollama`, or `auto` + this is set). |
| `OLLAMA_MODEL`      | `qwen2.5:7b-instruct`    | Local model tag. |
| `OLLAMA_TIMEOUT`    | `180`                    | Per-request timeout (seconds). |
| `CLAUDE_MODEL`      | `claude-sonnet-4-6`      | Claude model used for the API backend/fallback. |
| `ANTHROPIC_API_KEY` | —                        | Enables the Claude backend. |

GitHub Actions runs Claude-only (manual fallback). The M1 runs Ollama (primary).

**Model picks for 16 GB:**
- `qwen2.5:7b-instruct` *(default)* — best speed/quality balance, plenty of headroom.
- `qwen2.5:14b-instruct` — noticeably better fidelity, ~9 GB at Q4 (fits, tighter).
- `aya-expanse:8b` — Cohere's translation-tuned multilingual model; excellent Spanish.

## Run the pipeline on the M1 (outbound only)

The repurposed M1 is the production updater: it fetches feeds, translates locally
with Ollama, and **pushes `feed.json` outbound to GitHub** on a schedule. Every
connection is the Mac reaching *out* — nothing listens for inbound connections, so
there's no port to forward, no tunnel, and no attack surface from the internet.

Two one-time scripts, run on the Mac from the repo root:

```bash
# 1. Install + configure Ollama (model pull, always-on service, Spanish smoke test)
./scripts/setup-m1-ollama.sh
#    higher-fidelity model:  OLLAMA_MODEL=qwen2.5:14b-instruct ./scripts/setup-m1-ollama.sh

# 2. Install the scheduled local updater (venv, a test run, a launchd timer)
./scripts/setup-m1-local-pipeline.sh
```

That installs a launchd timer that runs `scripts/run-pipeline.sh` at 07:30 / 12:30 /
17:30 / 22:30 local time. Each run: `git pull` → translate via local Ollama → commit
→ `git push` (only when `feed.json` changed). Prereqs: `git push` already works for
this clone, and `sudo pmset -a sleep 0` so the Mac is awake at the scheduled times.

```bash
tail -f pipeline.log                 # watch runs
launchctl start com.senal.feed       # run now
launchctl list | grep com.senal.feed # check it's loaded
```

An optional Claude fallback (used only if Ollama errors) can be enabled per-machine:
`echo 'ANTHROPIC_API_KEY=sk-ant-...' > ~/.senal.env`.

### Reaching the M1 yourself

On your home network, SSH in normally (**System Settings → General → Sharing →
Remote Login**). Remote access from outside the LAN is intentionally **not** set up
— nothing is exposed to the internet. If you later want phone access from anywhere
*without* opening a port, `scripts/setup-m1-remote-access.sh` configures it over a
private Tailscale tailnet (and can install the Claude Code CLI so Claude runs on the
box). Until then, the box stays fully closed.

## Feeds Included

| Category  | Source                   |
|-----------|--------------------------|
| Tech      | Hacker News, The Verge, Ars Technica |
| News      | BBC News, The Guardian   |
| Sport     | BBC Sport                |
| Football  | Liverpool FC (Sky Sports), Wales Football (BBC) |
| Rugby     | Wales Rugby (BBC)        |
| MMA       | MMA Junkie, Bloody Elbow |

## Customisation

- **Add/remove feeds**: edit the `FEEDS` list in `fetch_and_translate.py`
- **Change item count per feed**: edit `MAX_ITEMS_PER_FEED`
- **Change schedule**: edit the `cron` line in `.github/workflows/daily.yml`
- **Language toggle**: the site has an ES/EN toggle built in — EN shows original text

## Estimated Claude API cost

~50 items × ~150 tokens each = ~7,500 tokens/day translated  
At Sonnet pricing this is well under $0.05/day.
