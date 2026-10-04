# Handover

Current state for a fresh session. Last updated 4 Oct 2026. Read this after `CLAUDE.md`.

## Where things stand

- Live and running: the Update feed workflow publishes `feed.json` twice a day (06:23 / 18:23 UTC) to GitHub Pages.
- Features in place: translation caching across runs, Message Batches API translation on Haiku, PWA (installable, offline), ES/EN toggle, tap-a-word dictionary, saved vocabulary with spaced-repetition review, optional World Cup results, ruff + pytest CI, Claude Code skills in `.claude/skills/`.
- Recent merged work:
  - #27 (6 Aug): removed two dead feeds (Damn Interesting, Nixintel).
  - #26 (3 Jul): Claude Code skills, hardened pipeline and CI, translation costs cut about 20×.
  - #24 (3 Jul): translation caching, tests and CI, PWA, word-tap fixes.
- No open issues.

## Waiting on the owner

- **#25 (closed, not merged):** "local-first pipeline on the M1". Decide whether local translation via the M1 server is still wanted; if so, open a fresh issue rather than reviving the old branch.
- **Duplicate repo:** `up160/fetchandtranslate` (no underscores) is an empty placeholder. Archive or delete it so sessions don't pick the wrong one.

## Next up

- Nothing queued. New work starts as an issue (see CLAUDE.md → How work is done).
