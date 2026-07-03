#!/usr/bin/env python3
"""
Feed health checker for SEÑAL.

Runs every feed in feeds.json through the REAL fetch path
(fetch_and_translate.fetch_feed) so results match production behaviour,
then prints a per-feed report and a dead/suspect summary.

Usage:
    python .claude/skills/check-feeds/check_feeds.py [name-or-url-substring]

No ANTHROPIC_API_KEY needed — nothing is translated.
"""

import sys
import os

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, REPO_ROOT)

import feedparser  # noqa: E402
from fetch_and_translate import FEEDS, fetch_feed  # noqa: E402


def main():
    needle = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    feeds = [
        f for f in FEEDS
        if needle in f["name"].lower() or needle in f["url"].lower()
    ]
    if not feeds:
        print(f"No feeds match {needle!r}. Configured feeds:")
        for f in FEEDS:
            print(f"  {f['name']}")
        return 1

    dead, suspect = [], []
    for f in feeds:
        # Raw parse first for status/bozo diagnostics...
        parsed = feedparser.parse(f["url"])
        status = getattr(parsed, "status", "n/a")
        bozo = parsed.get("bozo_exception")
        # ...then the real production path (UA, Reddit retry, image extraction).
        items = fetch_feed(f)
        with_img = sum(1 for i in items if i["image"])

        flag = "OK "
        if not items:
            flag = "DEAD"
            dead.append(f["name"])
        elif bozo:
            flag = "WARN"
            suspect.append(f["name"])

        print(f"[{flag}] {f['category']:11} {f['name']:35} "
              f"items={len(items)} images={with_img} http={status}"
              + (f" bozo={type(bozo).__name__}: {bozo}" if bozo else ""))

    print()
    print(f"{len(feeds)} feeds checked: "
          f"{len(feeds) - len(dead) - len(suspect)} ok, "
          f"{len(suspect)} suspect, {len(dead)} dead")
    if dead:
        print("Dead:", ", ".join(dead))
    if suspect:
        print("Suspect (parsed with warnings):", ", ".join(suspect))
    return 2 if dead else 0


if __name__ == "__main__":
    raise SystemExit(main())
