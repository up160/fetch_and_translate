# SEÑAL // Feed Diario

Daily RSS reader that fetches English-language news and translates to Spanish via Claude API. Hosted on GitHub Pages.

## Structure

```
├── fetch_and_translate.py   # Fetch + translate script (caches across runs)
├── feeds.json               # Feed sources + config
├── feed.json                # Generated output (committed by CI)
├── index.html               # Static site (PWA)
├── manifest.webmanifest     # PWA manifest
├── sw.js                    # Service worker (offline shell + feed cache)
├── icon.svg                 # App / install icon
├── requirements.txt         # Runtime deps
├── requirements-dev.txt     # + lint/test deps
├── tests/                   # Unit tests (pytest)
└── .github/
    └── workflows/
        ├── update-feed.yml  # Scheduled fetch/translate job
        └── ci.yml           # Lint + tests on PRs
```

## Setup

### 1. Create GitHub repo & enable Pages

- Push this directory to a new GitHub repo
- Go to **Settings → Pages → Source**: set to `Deploy from branch`, branch `main`, folder `/root`
- Your site will be at `https://<your-username>.github.io/<repo-name>/`

### 2. Add your Anthropic API key

- Go to **Settings → Secrets and variables → Actions**
- Add a secret named `ANTHROPIC_API_KEY` with your key from console.anthropic.com

### 3. Generate initial feed.json

Run locally first to verify everything works:

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python fetch_and_translate.py
```

Commit the resulting `feed.json`, then push. The site will render immediately.

### 4. Let it run automatically

The `Update feed` GitHub Action runs twice a day. You can also trigger it manually from the **Actions** tab → **Update feed** → **Run workflow**.

Unchanged items are **not** re-translated: each run reuses the Spanish text from the previous `feed.json` and only sends genuinely new items to Claude, so the recurring schedule costs very little.

## Feeds Included

See `feeds.json` for the live list. Current categories:

| Category    | Sources |
|-------------|---------|
| Mundial     | World Cup results (football-data.org) |
| World Cup   | Guardian World Cup 2026, BBC Football |
| Parenting   | r/daddit |
| Interesante | Atlas Obscura, Damn Interesting, 99% Invisible, Kottke, Defector |
| Tech        | Hacker News, Ars Technica |
| News        | BBC News, The Guardian |
| Security    | Krebs on Security, Bellingcat, Nixintel |
| Football    | Wales Football (BBC + WalesOnline) |
| Rugby       | Wales Rugby (BBC), Squidge Rugby, Inside Welsh Rugby |

## Customisation

- **Add/remove feeds**: edit the `feeds` array in `feeds.json`
- **Change item count per feed**: edit `max_items_per_feed` in `feeds.json`
- **Disable World Cup results** (after the tournament): set `"world_cup_results": false` in `feeds.json`
- **Change schedule**: edit the `cron` line in `.github/workflows/update-feed.yml`
- **Language toggle**: the site has an ES/EN toggle built in — EN shows original text

Feeds that quietly stop updating are flagged in the job log with a `⚠ STALE` warning (newest item older than 45 days) so they can be pruned.

## Install as an app (PWA)

The site is a Progressive Web App: open it on mobile and choose **Add to Home Screen**. It installs with its own icon, launches full-screen, and the last fetched feed is cached so it still opens and reads **offline**.

## Development

```bash
pip install -r requirements-dev.txt
ruff check .        # lint
pytest              # unit tests (no network / API key needed)
```

CI (`.github/workflows/ci.yml`) runs lint + tests on every pull request.

## Estimated Claude API cost

Cost is dominated by **output** tokens (the generated Spanish), which are priced
~5× higher than input. A full run translating all ~105 items is ~22K input +
~21K output tokens.

Three things keep the bill small:

- **Per-run caching** — only genuinely new items are translated each run, not the
  whole feed. After the first run a typical run translates a handful of items.
- **Model** — translation uses `claude-haiku-4-5` ($1/$5 per 1M in/out), ~3× cheaper
  than Sonnet and ample for news headlines/summaries.
- **Twice-daily schedule** — limits how often new items are translated.

With all three, expect roughly **$0.05–0.15/day**. (A naïve setup — re-translating
every item, 4×/day, on Sonnet — runs ~$1.50/day, mostly output tokens.)
