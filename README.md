# SEÑAL // Feed Diario

Daily RSS reader that fetches English-language news, translates it to Spanish (Spain) via the Claude API, and publishes as a static site on GitHub Pages. Includes an ES/EN toggle, tap-a-word dictionary lookups, and a saved-vocabulary page with spaced-repetition review.

## Structure

```
├── fetch_and_translate.py     # The pipeline: fetch → translate → feed.json
├── feeds.json                 # Feed sources config (edit this to add/remove feeds)
├── feed.json                  # Generated output (committed by CI — don't hand-edit)
├── index.html                 # The entire site: one self-contained static file
├── requirements.txt
├── CLAUDE.md                  # Project guide for Claude Code sessions
├── .claude/skills/            # Claude Code skills (feed checks, previews, CI debug…)
└── .github/workflows/
    └── update-feed.yml        # Scheduled GitHub Action (every 6h)
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

The GitHub Action runs every 12 hours (06:23 / 18:23 UTC) and only commits when `feed.json` actually changed. You can also trigger it manually from the **Actions** tab → **Update feed** → **Run workflow**.

> GitHub disables scheduled workflows after ~60 days without repo activity — re-enable from the Actions tab if updates stop.

## Feeds Included

| Category    | Sources                                                        |
|-------------|----------------------------------------------------------------|
| World Cup   | World Cup 2026 (Guardian), BBC Football                        |
| Parenting   | r/daddit                                                       |
| Interesante | Atlas Obscura, Damn Interesting, 99% Invisible, Kottke, Defector |
| Tech        | Hacker News, Ars Technica                                      |
| News        | BBC News, The Guardian                                         |
| Security    | Krebs on Security, Bellingcat, Nixintel                        |
| Football    | Wales Football (BBC), Wales Football (WalesOnline)             |
| Rugby       | Wales Rugby (BBC), Squidge Rugby (YouTube), Inside Welsh Rugby |

## Customisation

- **Add/remove feeds**: edit `feeds.json` (and update the table above). Feeds are fetched through a custom user agent and failures are non-fatal — a dead feed never breaks the build.
- **Items per feed**: `max_items_per_feed` in `feeds.json`
- **Schedule**: the `cron` line in `.github/workflows/update-feed.yml`
- **Language toggle**: the site has an ES/EN toggle built in — EN shows original text
- **Translation style**: `TRANSLATE_PROMPT` in `fetch_and_translate.py`

## Estimated Claude API cost

The pipeline is aggressively cost-optimised: translations are reused across runs (only new or changed items hit the API), proper-noun headlines are confirmed once and never re-sent, the model is Haiku 4.5 ($1/$5 per million tokens), and calls go through the Message Batches API at 50% of standard price. At the twice-daily schedule that works out to roughly **$0.05/day (~$20/year)** — a $5 credit balance lasts about three months.
