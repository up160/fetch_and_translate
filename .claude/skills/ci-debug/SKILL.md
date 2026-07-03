---
name: ci-debug
description: Diagnose and fix the scheduled GitHub Action (update-feed.yml) — feed.json not updating, workflow failures, secret problems, schedule drift, or push conflicts. Use when asked "why hasn't the site updated", "the action is failing", or when changing the schedule/workflow.
---

# Debug the daily feed workflow

`.github/workflows/update-feed.yml` runs at 00:23/06:23/12:23/18:23 UTC and commits `feed.json` only when it changed. Use the GitHub MCP tools (`mcp__github__actions_list`, `actions_get`, `get_job_logs`) — there is no `gh` CLI here.

## First moves

1. Check `feed.json`'s `generated_at` field and the last `Update feed.json` commit date — that tells you when the pipeline last succeeded, before reading any logs.
2. List recent runs of the "Update feed" workflow and get logs for the newest failure (`get_job_logs` with `failed_only: true`).

## Failure taxonomy

- **`ANTHROPIC_API_KEY environment variable not set`** → the repo secret is named **`ANTHROPIC_SECRET_KEY`** (mapped to the `ANTHROPIC_API_KEY` env var in the workflow — intentional, don't rename the env side). The secret is missing/expired at repo Settings → Secrets → Actions. You can't read or set secrets; tell the user exactly which name to (re)create.
- **`✗ <feed name>` lines but run green** → per-feed failures are non-fatal by design. Only act if the same feed fails across several runs — then use the check-feeds skill.
- **`✗ Chunk N–M failed`** → translation API errors (rate limit, overload). One-offs self-heal via the retry pass and the next 6-hour run. Persistent 401s = key problem (see above).
- **Push step fails (non-fast-forward)** → a human/agent pushed to main between checkout and push. Rare; fix by adding a `git pull --rebase origin main` before the push in the commit step, not by force-pushing.
- **No runs at all around a scheduled slot** → GitHub drops scheduled slots under load (that's why it runs 4×/day) and **disables schedules entirely after ~60 days without repo activity**. If the last run is old and the repo has been quiet, the user needs to re-enable the workflow in the Actions tab; suggest a manual `workflow_dispatch` (`actions_run_trigger`) to confirm it still works.
- **"No changes" every run** → not a failure; feeds produced identical content. Only suspicious if it persists >24h — then dry-run the fetch locally with check-feeds.

## Kicking it manually

Trigger a run with `mcp__github__actions_run_trigger` on `update-feed.yml` (ref `main`), then poll the run result. Do this after any workflow or pipeline fix to verify end-to-end, since local runs here may lack the API key.

## Editing the workflow

- Keep the off-peak minute (`:23`) in any new cron — on-the-hour slots are the most heavily dropped.
- Keep `permissions: contents: write` — the job commits to main.
- The commit step's `git diff --cached --quiet && exit 0` no-change guard must survive any edit, or the repo gets a junk commit every 6 hours.
- Remember README says "daily at 07:00 UTC" — update it if you change the schedule.
