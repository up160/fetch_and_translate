---
name: check-feeds
description: Check that every RSS feed in feeds.json is alive and returning items, and dry-run the real fetch pipeline without needing an API key. Use when a feed seems dead, when feed.json is missing a source/category, after editing feeds.json or fetch logic, or when asked to "check the feeds" / "why is X missing from the site".
---

# Check feeds / dry-run the fetch pipeline

## Quick health check (no API key needed)

```bash
# System pip can fail building sgmllib3k (Debian setuptools bug) — use a venv if so:
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python .claude/skills/check-feeds/check_feeds.py
```

If **every** feed reports dead with `Tunnel connection failed: 403 Forbidden`, that's the sandbox's egress proxy blocking feed hosts, not the feeds — verification has to happen via a manual CI run (see the ci-debug skill) instead of locally.

The script imports the **real** code path (`fetch_feed` from `fetch_and_translate.py`), so it exercises the same user agent, Reddit retry, image extraction and summary stripping as production. It prints per-feed: item count, HTTP status, bozo (parse) errors, and whether an image was found — then a summary of dead/suspect feeds.

Filter to one feed while debugging: `python .claude/skills/check-feeds/check_feeds.py reddit`
(case-insensitive substring match against feed name or URL).

## Interpreting results

- **0 items, HTTP 200, bozo error** → the feed URL now returns HTML or a redirect page, not XML. Fetch the URL with curl and look at the first lines; the publisher likely moved the feed.
- **0 items from Reddit** → rate limiting (429). The pipeline already retries once; a second consecutive failure in CI usually self-heals next run. Only escalate if it fails across multiple days of CI runs.
- **0 items, network error** → could be this sandbox's egress proxy, not the feed. Verify with `curl -sI <url>` before declaring a feed dead — CI runs from GitHub runners with open egress.
- **Items but no images** → fine for text-first sources; only investigate if the site previously showed images for that source.

## Cross-checking against the live output

`feed.json` in the repo is the last CI output. To see which sources actually made it into the current build:

```bash
python -c "
import json
from collections import Counter
d = json.load(open('feed.json'))
for (cat, src), n in Counter((i['category'], i['source']) for i in d['items']).items():
    print(f'{cat:12} {src:35} {n}')
print('generated_at:', d['generated_at'])
"
```

A source configured in `feeds.json` but absent here failed at the last CI run — check the Actions logs for the ✗ line.

## Rules

- Never let a fix make a feed failure fatal: `fetch_feed` must keep returning `[]` on error. A dead feed must never break the daily build.
- Don't hand-edit `feed.json` to patch in missing items — it's regenerated every 6 hours.
