---
name: add-feed
description: Add, remove, or replace an RSS feed source properly end-to-end — validate the URL, pick a category, update feeds.json and the README table, and verify through the real fetch path. Use when asked to "add a feed", "follow X on the site", "remove Y", or "swap Z for a better source".
---

# Add / remove / replace a feed source

All source config lives in `feeds.json` — never hardcode feeds in the Python.

## Adding a feed

1. **Find the real feed URL.** Common patterns when the user only gives a site name:
   - WordPress blogs: `<site>/feed/`
   - Substack: `<name>.substack.com/feed`
   - YouTube channel: `https://www.youtube.com/feeds/videos.xml?channel_id=<UC...>` (need the `UC...` channel ID, not the @handle — fetch the channel page and grep for `channelId`)
   - Reddit: `https://www.reddit.com/r/<sub>/.rss`
   - BBC sections: `https://feeds.bbci.co.uk/...` — check an existing BBC entry for the shape
   - Guardian sections: append `/rss` to any section URL
   - Otherwise fetch the site's HTML and look for `<link rel="alternate" type="application/rss+xml">`

2. **Validate before editing.** Run the health checker against just this URL by temporarily adding the entry to `feeds.json`, then:
   ```bash
   python .claude/skills/check-feeds/check_feeds.py <name-substring>
   ```
   It must return items through the real fetch path. If it returns 0 items here but `curl -sI <url>` shows the sandbox proxy blocking it, say so — it may still work from GitHub's runners.

3. **Choose the category.** Reuse an existing one where it fits (`World Cup`, `Parenting`, `Interesante`, `Tech`, `News`, `Security`, `Football`, `Rugby`). A new category is fine — the frontend renders categories dynamically from `feed.json` — but confirm the name with the user since it's user-facing site copy (Spanish-leaning names like `Interesante`/`Mundial` are the house style).

4. **Edit `feeds.json`**, keeping the existing grouping/alignment style (entries grouped by category with a blank line between groups, aligned columns).

5. **Update the README "Feeds Included" table** to match.

6. **Verify**: re-run the checker for the new feed and confirm item count > 0 and sensible titles.

## Removing / replacing

- Delete the entry from `feeds.json` and the README table. Don't touch `feed.json` — stale items age out on the next CI run.
- When replacing a dead source, keep the same category so the site section survives.

## Things that bite

- Some hosts block generic user agents; the pipeline already sends `senal-feed-reader/1.0`. If a feed 403s in the checker, test with that exact UA via curl before concluding it's blocked.
- `max_items_per_feed` (currently 5) is global. Don't add a firehose feed (e.g. a full HN front-page mirror) without considering it'll still only contribute 5 items but may crowd translation chunks with junk.
- Every added feed costs translation tokens daily (~5 items × ~150 tokens). One feed is noise; ten is a cost conversation — mention it if the user is bulk-adding.
