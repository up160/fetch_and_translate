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

The GitHub Action (`update-feed.yml`) runs every 6 hours (00:23 / 06:23 / 12:23 /
18:23 UTC) and only commits when `feed.json` actually changes. You can also trigger
it manually from the **Actions** tab → **Update feed** → **Run workflow**.

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

GitHub Actions sets none of the Ollama vars, so CI keeps using Claude unchanged.

### Local translation on an M1 (free, no API credits)

Run translation on a repurposed M1 / 16 GB box instead of paying per token:

```bash
# on the M1
brew install ollama && ollama serve
ollama pull qwen2.5:7b-instruct      # ~5 GB at Q4; fast and good Spanish
export TRANSLATE_BACKEND=ollama
# export ANTHROPIC_API_KEY=sk-ant-... # optional: Claude fallback if Ollama errors
python fetch_and_translate.py
```

**Model picks for 16 GB:**
- `qwen2.5:7b-instruct` *(default)* — best speed/quality balance, plenty of headroom.
- `qwen2.5:14b-instruct` — noticeably better fidelity, ~9 GB at Q4 (fits, tighter).
- `aya-expanse:8b` — Cohere's translation-tuned multilingual model; excellent Spanish.

To run the *whole pipeline* on the M1, point a GitHub Actions **self-hosted runner**
at the box, or keep CI on GitHub and expose Ollama over a private network (e.g.
Tailscale) by setting the `OLLAMA_HOST` secret to the box's tailnet address.

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
