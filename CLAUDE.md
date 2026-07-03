# SEÑAL // Feed Diario

Daily RSS reader: fetches English-language feeds, translates to Spanish (Spain) via the Claude API, publishes as a static site on GitHub Pages.

## Architecture

- `fetch_and_translate.py` — the whole pipeline: fetch feeds → optional World Cup results → dedupe by id → reuse previous translations for unchanged items → translate the rest in chunks of 8 via Claude → write `feed.json`.
- `feeds.json` — feed sources config (category, name, url) + `max_items_per_feed`. Edit this to add/remove feeds, not the Python.
- `feed.json` — **generated output, committed by CI**. Never hand-edit; changes are overwritten on the next scheduled run.
- `index.html` — the entire frontend: single self-contained file (inline CSS + JS), loads `./feed.json` client-side, ES/EN toggle built in.
- `.github/workflows/update-feed.yml` — runs every 6h (00:23/06:23/12:23/18:23 UTC) + manual dispatch; commits `feed.json` only when it changed.

## Gotchas

- The workflow maps the repo secret `ANTHROPIC_SECRET_KEY` to the env var `ANTHROPIC_API_KEY` — the names intentionally differ. Don't "fix" this without changing the repo secret too.
- `FOOTBALL_API_KEY` is optional; World Cup results silently skip when unset. Nothing in the pipeline may raise on a missing/failed source — a dead feed must never break the daily build.
- The workflow's final "Alert if translation is broken" step turns the run red (after committing) when >80% of items are untranslated — that's how a dead key/empty credit balance surfaces. Don't remove it, and don't make the Python itself exit non-zero on translation failure.
- Translation model is pinned in `_translate_chunk` (`claude-sonnet-4-6`). Cost matters here (~50 items/day) — don't upgrade to a bigger model without being asked.
- The translator falls back to English per item and does a targeted retry pass for items left untranslated. Terse proper-noun headlines legitimately stay identical to English.
- Reddit rate-limits (429 → empty feed); `fetch_feed` already retries once after a 6s sleep. YouTube/Substack/Reddit need the custom `USER_AGENT`.
- `feed.json` item IDs are md5 of the link — stable across runs. The pipeline relies on this twice: `dedupe_items` drops the same story surfacing from overlapping feeds, and the previous run's translations are reused for items whose id and English text are unchanged (items still equal to English go back through the API, preserving the old retry behaviour).

## Local dev

```bash
# System pip may fail building sgmllib3k (Debian setuptools bug) — use a venv:
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python .claude/skills/check-feeds/check_feeds.py   # fetch-only dry run, no API key needed
export ANTHROPIC_API_KEY=sk-ant-...                # only needed for full pipeline
.venv/bin/python fetch_and_translate.py
python -m http.server 8000                          # then open http://localhost:8000
```

In restricted remote sessions the egress proxy may 403 all feed hosts — the dry run then reports every feed dead. That's the sandbox, not the feeds; verify via a manual CI run instead.

There are no tests; verification is running the pipeline (or the fetch-only dry run) and eyeballing output. Keep it that way unless asked.

## Conventions

- Python: stdlib + `feedparser` + `anthropic` only. No new dependencies without a strong reason.
- Frontend: everything stays in the single `index.html` — no build step, no frameworks, no external JS. It must work served as plain static files from GitHub Pages.
- Site copy/UI text is Spanish; code comments and commit messages are English.
- When adding a feed, update the README "Feeds Included" table too.
