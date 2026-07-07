# SEÑAL // Feed Diario

Daily RSS reader that fetches English-language news, translates it to Spanish (Spain) via the Claude API, and publishes as a static site on GitHub Pages. Includes an ES/EN toggle, tap-a-word dictionary lookups, and a saved-vocabulary page with spaced-repetition review.

## Structure

```
├── fetch_and_translate.py   # Fetch + translate pipeline (caches across runs)
├── feeds.json               # Feed sources + config (edit this to add/remove feeds)
├── feed.json                # Generated output (committed by CI — don't hand-edit)
├── index.html               # Static site (PWA)
├── manifest.webmanifest     # PWA manifest
├── sw.js                    # Service worker (offline shell + feed cache)
├── icon.svg                 # App / install icon
├── requirements.txt         # Runtime deps
├── requirements-dev.txt     # + lint/test deps
├── tests/                   # Unit tests (pytest)
├── CLAUDE.md                # Project guide for Claude Code sessions
├── .claude/skills/          # Claude Code skills (feed checks, previews, CI debug…)
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

### 2. Add your API keys

Go to **Settings → Secrets and variables → Actions** and add:

- `ANTHROPIC_SECRET_KEY` — your key from console.anthropic.com. **Note the name**: the workflow maps this secret to the `ANTHROPIC_API_KEY` env var; the names intentionally differ.
- `FOOTBALL_API_KEY` *(optional)* — a football-data.org key for World Cup results. When unset, results are silently skipped.

### 3. Generate initial feed.json

Run locally first to verify everything works:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
.venv/bin/python fetch_and_translate.py
```

Commit the resulting `feed.json`, then push. The site will render immediately.

### 4. Let it run automatically

The `Update feed` GitHub Action runs twice a day (06:23 / 18:23 UTC) and only
commits when `feed.json` actually changed. You can also trigger it manually from
the **Actions** tab → **Update feed** → **Run workflow**.

Unchanged items are **not** re-translated: each run reuses the Spanish text from
the previous `feed.json` and only sends genuinely new items to Claude. A run over
an unchanged feed makes **zero** API calls, so the number of runs barely affects
cost — if fresher World Cup scores matter, add slots back to the cron line.

> GitHub disables scheduled workflows after ~60 days without repo activity — re-enable from the Actions tab if updates stop.

## Feeds Included

See `feeds.json` for the live list. Current categories:

| Category    | Sources |
|-------------|---------|
| Mundial     | World Cup results (football-data.org) |
| World Cup   | Guardian World Cup 2026, BBC Football |
| Parenting   | r/daddit |
| Interesante | Atlas Obscura, 99% Invisible, Kottke, Defector |
| Tech        | Hacker News, Ars Technica |
| News        | BBC News, The Guardian |
| Security    | Krebs on Security, Bellingcat |
| Football    | Wales Football (BBC + WalesOnline) |
| Rugby       | Wales Rugby (BBC), Squidge Rugby, Inside Welsh Rugby |

## Customisation

- **Add/remove feeds**: edit the `feeds` array in `feeds.json` (and update the table above). Feeds are fetched through a custom user agent and failures are non-fatal — a dead feed never breaks the build.
- **Change item count per feed**: edit `max_items_per_feed` in `feeds.json`
- **Disable World Cup results** (after the tournament): set `"world_cup_results": false` in `feeds.json`
- **Change schedule**: edit the `cron` line in `.github/workflows/update-feed.yml`
- **Language toggle**: the site has an ES/EN toggle built in — EN shows original text
- **Translation style**: `TRANSLATE_PROMPT` in `fetch_and_translate.py`

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

The bill is driven by one number: **how many genuinely new items get translated
per day**. Because translations are cached (by item id + unchanged English text),
re-running over the same items costs nothing — run frequency is irrelevant.

**Per item**, at Haiku 4.5 through the Message Batches API (50% of standard
price — the pipeline submits every run as one batch):

| | tokens/item | batch price (Haiku 4.5) | $/item |
|---|---|---|---|
| Input  | ~310 | $0.50 / 1M | $0.00016 |
| Output | ~300 | $2.50 / 1M | $0.00075 |
| **Total** | | | **~$0.0009** |

**Per day** = new items × ~$0.0009:

| Scenario | New items/day | Daily cost |
|---|---|---|
| Quiet day (no live football) | ~30 | **~$0.03** |
| World Cup group stage (many results + news) | ~50–60 | **~$0.05** |
| First run ever (translates all ~105 at once) | 105 | ~$0.10 (one-off) |

So expect roughly **$0.03–0.06/day (~$1–2/month)** in steady state — a $5
balance lasts months. Every run prints an `API usage this run: … ≈ $X` line in
the Actions log with the *measured* spend, so cost drift is visible immediately.

What keeps it there:

- **Per-run caching** — only genuinely new items are translated. A finished World
  Cup result never changes its score, so it translates once and is reused forever.
  Headlines that legitimately stay identical to English (proper nouns, score
  lines) are confirmed once (`es_confirmed`) and never re-sent either.
- **Model** — `claude-haiku-4-5` ($1/$5 per 1M in/out), ~3× cheaper than Sonnet and
  ample for news headlines. Output tokens dominate, so this is the biggest lever.
- **Batches API** — all chunks go up as one async batch at half price, with a
  direct-call fallback if batching is unavailable.

The earlier ~$1.50/day burn came from the *pre-caching* setup: re-translating
**every** item, four times a day, on Sonnet. Caching + Haiku + batching, not
fewer runs, is what fixed it.
