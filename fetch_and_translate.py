#!/usr/bin/env python3
"""
RSS Fetcher + Spanish Translator
Fetches RSS feeds, translates to Spanish via Claude API, outputs feed.json
"""

import json
import os
import time
import hashlib
from datetime import datetime, timezone
from typing import Optional

import feedparser
import anthropic

# Reddit (and some other hosts) block feedparser's default user agent
feedparser.USER_AGENT = "fetch_and_translate-rss-reader/1.0"

# ─── Feed Sources (loaded from feeds.json) ──────────────────────────────────

def load_config():
    """Load feed configuration from feeds.json in the same directory."""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feeds.json")
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)

CONFIG = load_config()
FEEDS = CONFIG["feeds"]
MAX_ITEMS_PER_FEED = CONFIG.get("max_items_per_feed", 5)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# ─── Fetch Feeds ─────────────────────────────────────────────────────────────

def fetch_feed(feed_config: dict) -> list[dict]:
    """Fetch and parse a single RSS feed."""
    try:
        parsed = feedparser.parse(feed_config["url"])
        items = []
        for entry in parsed.entries[:MAX_ITEMS_PER_FEED]:
            title = entry.get("title", "").strip()
            summary = entry.get("summary", entry.get("description", "")).strip()
            # Strip basic HTML tags from summary
            import re
            summary = re.sub(r"<[^>]+>", "", summary).strip()
            summary = summary[:400]  # Cap length for translation cost control

            if not title:
                continue

            items.append({
                "id": hashlib.md5(entry.get("link", title).encode()).hexdigest()[:10],
                "title_en": title,
                "summary_en": summary,
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "category": feed_config["category"],
                "source": feed_config["name"],
            })
        print(f"  ✓ {feed_config['name']}: {len(items)} items")
        return items
    except Exception as e:
        print(f"  ✗ {feed_config['name']}: {e}")
        return []


def fetch_all_feeds() -> list[dict]:
    """Fetch all configured RSS feeds."""
    print("Fetching RSS feeds...")
    all_items = []
    for feed in FEEDS:
        items = fetch_feed(feed)
        all_items.extend(items)
        time.sleep(0.5)  # polite delay
    print(f"Total items fetched: {len(all_items)}")
    return all_items


# ─── Translate ────────────────────────────────────────────────────────────────

def translate_batch(items: list[dict], client: anthropic.Anthropic) -> list[dict]:
    """
    Translate titles and summaries to Spanish in a single Claude API call.
    Batching all items together is efficient and cheap.
    """
    print("Translating to Spanish via Claude...")

    # Build compact JSON payload for translation
    to_translate = [
        {"id": item["id"], "title": item["title_en"], "summary": item["summary_en"]}
        for item in items
    ]

    prompt = f"""You are a professional translator. Translate the following news items from English to Spanish.
Return ONLY a valid JSON array — no markdown, no explanation, no preamble.
Each object must have: id, title_es, summary_es.
Keep titles punchy and natural. Summaries should read as fluent Spanish, not literal translations.
Keep proper nouns (team names, places, brand names) as-is.

Items to translate:
{json.dumps(to_translate, ensure_ascii=False)}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        translations = json.loads(raw)
        translation_map = {t["id"]: t for t in translations}

        # Merge translations back into items
        for item in items:
            t = translation_map.get(item["id"], {})
            item["title_es"] = t.get("title_es", item["title_en"])
            item["summary_es"] = t.get("summary_es", item["summary_en"])

        print(f"  ✓ Translated {len(translations)} items")
    except Exception as e:
        print(f"  ✗ Translation failed: {e}")
        # Fallback: use English
        for item in items:
            item["title_es"] = item["title_en"]
            item["summary_es"] = item["summary_en"]

    return items


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Fetch
    items = fetch_all_feeds()

    if not items:
        print("No items fetched. Exiting.")
        return

    # Translate
    items = translate_batch(items, client)

    # Build output
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "item_count": len(items),
        "items": items,
    }

    # Write feed.json to repo root (where index.html lives)
    out_path = os.path.join(os.path.dirname(__file__), "feed.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Done. feed.json written with {len(items)} items.")


if __name__ == "__main__":
    main()
