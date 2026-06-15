#!/usr/bin/env python3
"""
RSS Fetcher + Spanish Translator
Fetches RSS feeds, translates to Spanish via Claude API, outputs feed.json
"""

import json
import os
import re
import time
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional

import feedparser
import anthropic

# YouTube, Substack, Reddit and some hosts behave better with a descriptive UA
# (and several block feedparser's default agent outright).
USER_AGENT = "senal-feed-reader/1.0"
feedparser.USER_AGENT = USER_AGENT

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
FOOTBALL_API_KEY = os.environ.get("FOOTBALL_API_KEY")

SUMMARY_CAP = 900  # max chars of summary kept for translation
STALE_FEED_DAYS = 45  # warn if a feed's newest item is older than this

# ─── Fetch Feeds ─────────────────────────────────────────────────────────────

def extract_image(entry, raw_html: str) -> str:
    """
    Find the first usable image URL for an entry.
    Order: media:content → media:thumbnail (YouTube) → enclosure →
           og:image or <img> in the summary/content HTML. "" if none.
    """
    # media:content — feedparser exposes as entry.media_content.
    # Only use it if it's an image (YouTube's media:content is the video itself).
    for mc in entry.get("media_content", []) or []:
        url = mc.get("url")
        if not url:
            continue
        medium = str(mc.get("medium", ""))
        mtype = str(mc.get("type", ""))
        if medium == "image" or mtype.startswith("image") or (not medium and not mtype):
            return url
    # media:thumbnail — YouTube feeds carry the video thumbnail here
    for mt in entry.get("media_thumbnail", []) or []:
        if mt.get("url"):
            return mt["url"]
    # enclosure links (rel="enclosure" with an image type)
    for link in entry.get("links", []) or []:
        if link.get("rel") == "enclosure" and str(link.get("type", "")).startswith("image"):
            if link.get("href"):
                return link["href"]
    # Fallback: scan summary/content HTML for og:image or an <img> tag
    html = raw_html or ""
    for c in entry.get("content", []) or []:
        html += " " + (c.get("value") or "")
    og = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html, re.I)
    if og:
        return og.group(1)
    img = re.search(r'<img[^>]+src=["\']([^"\']+)', html, re.I)
    if img:
        return img.group(1)
    return ""


def newest_entry_age_days(parsed) -> Optional[float]:
    """Age in days of the most recent entry in a parsed feed, or None if no
    entry carries a usable date."""
    newest = None
    for entry in parsed.entries:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if not t:
            continue
        dt = datetime(*t[:6], tzinfo=timezone.utc)
        if newest is None or dt > newest:
            newest = dt
    if newest is None:
        return None
    return (datetime.now(timezone.utc) - newest).total_seconds() / 86400


def fetch_feed(feed_config: dict) -> list[dict]:
    """Fetch and parse a single RSS feed."""
    try:
        url = feed_config["url"]
        parsed = feedparser.parse(url)
        # Reddit rate-limits bursts of requests (HTTP 429) and returns an empty
        # feed; back off briefly and retry once.
        if not parsed.entries and "reddit.com" in url:
            time.sleep(6)
            parsed = feedparser.parse(url)

        # Surface feeds that have quietly gone stale (like the old Scarlets feed
        # that hadn't updated since 2022) so they can be pruned.
        age = newest_entry_age_days(parsed)
        if age is not None and age > STALE_FEED_DAYS:
            print(f"  ⚠ STALE: {feed_config['name']} — newest item {int(age)} days old")

        items = []
        for entry in parsed.entries[:MAX_ITEMS_PER_FEED]:
            title = entry.get("title", "").strip()
            raw_summary = entry.get("summary", entry.get("description", ""))

            image = extract_image(entry, raw_summary)

            # Strip basic HTML tags from summary, then cap length
            summary = re.sub(r"<[^>]+>", "", raw_summary).strip()
            summary = re.sub(r"\s+", " ", summary)
            summary = summary[:SUMMARY_CAP]

            if not title:
                continue

            items.append({
                "id": hashlib.md5(entry.get("link", title).encode()).hexdigest()[:10],
                "title_en": title,
                "summary_en": summary,
                "image": image,
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


# ─── World Cup results (football-data.org) ──────────────────────────────────

def fetch_world_cup_results(days_back: int = 3) -> list[dict]:
    """
    Fetch recent FINISHED World Cup matches from football-data.org and return
    them as feed items (category 'Mundial'). Returns [] on any failure or if
    FOOTBALL_API_KEY is not set — this must never break the daily build.
    """
    if not FOOTBALL_API_KEY:
        print("Mundial: FOOTBALL_API_KEY not set — skipping World Cup results.")
        return []

    import urllib.request
    import urllib.error

    today = datetime.now(timezone.utc).date()
    date_from = (today - timedelta(days=days_back)).isoformat()
    date_to = today.isoformat()
    url = (
        "https://api.football-data.org/v4/competitions/WC/matches"
        f"?status=FINISHED&dateFrom={date_from}&dateTo={date_to}"
    )

    try:
        req = urllib.request.Request(
            url,
            headers={"X-Auth-Token": FOOTBALL_API_KEY, "User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Mundial: World Cup results fetch failed ({e}) — skipping.")
        return []

    matches = data.get("matches", [])
    items = []
    for m in matches:
        try:
            home = m["homeTeam"].get("name") or m["homeTeam"].get("shortName") or "?"
            away = m["awayTeam"].get("name") or m["awayTeam"].get("shortName") or "?"
            ft = m.get("score", {}).get("fullTime", {})
            hs, as_ = ft.get("home"), ft.get("away")
            if hs is None or as_ is None:
                continue
            date_str = (m.get("utcDate") or "")[:10]
            stage = (m.get("stage") or "").replace("_", " ").title()
            group = m.get("group")
            context = " · ".join(x for x in [stage, group] if x) or "World Cup"

            items.append({
                "id": "wc" + hashlib.md5(str(m.get("id", f"{home}{away}{date_str}")).encode()).hexdigest()[:8],
                "title_en": f"{home} {hs}–{as_} {away}",
                "summary_en": f"{context}. Played on {date_str}.",
                "image": "",
                "link": "",
                "published": m.get("utcDate", ""),
                "category": "Mundial",
                "source": "Resultados del Mundial",
            })
        except Exception:
            continue

    print(f"Mundial: {len(items)} World Cup results.")
    return items


# ─── Translate ────────────────────────────────────────────────────────────────

TRANSLATE_PROMPT = """You are a professional news translator producing Spanish (Spain) copy for a daily reader.
Translate each item from English to Spanish.

Guidelines:
- Write natural, fluent, idiomatic Spanish — never a literal word-for-word rendering.
- Use a journalistic register: clear, concise, neutral news tone. Titles stay punchy like real headlines.
- Keep proper nouns untranslated: team names, club names, player names, place names, brands,
  product names and company names (e.g. Scarlets, Bellingcat, Cardiff, Hacker News). Use the
  standard Spanish exonym for countries (e.g. Mexico->México, South Africa->Sudáfrica).
- Translate sports, tech and security/OSINT terminology the way Spanish-language media actually
  uses it; keep widely-used English terms (e.g. ransomware, hacker, try, scrum) when that is the norm.
- Preserve meaning and any numbers, scores and dates exactly.
- If a summary is empty, return an empty string for summary_es.

Return ONLY a valid JSON array — no markdown, no code fences, no explanation, no preamble.
Each object must have exactly these keys: id, title_es, summary_es.

Items to translate:
"""


def _strip_code_fence(raw: str) -> str:
    """Remove a leading ```json / ``` fence the model sometimes adds."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def _apply_translations(chunk: list[dict], translations: list[dict]) -> int:
    """
    Apply a parsed translation array onto a chunk in place.
    Pure (no network) so it can be unit-tested. Returns items actually changed.

    Match by id (coerced to str). The model sometimes returns the translated
    text under the *input* key names ("title"/"summary") instead of the
    requested "title_es"/"summary_es" — accept either, or fall back positionally.
    """
    by_id = {str(t.get("id")): t for t in translations}

    def pick(t, primary, secondary):
        v = t.get(primary)
        if v is None:
            v = t.get(secondary)
        return v

    changed = 0
    for idx, item in enumerate(chunk):
        t = by_id.get(str(item["id"]))
        if t is None and idx < len(translations):
            t = translations[idx]
        t = t or {}
        title_es = pick(t, "title_es", "title")
        summary_es = pick(t, "summary_es", "summary")
        item["title_es"] = title_es if title_es else item["title_en"]
        item["summary_es"] = summary_es if summary_es is not None else item["summary_en"]
        if item["title_es"] != item["title_en"]:
            changed += 1
    return changed


def _translate_chunk(chunk: list[dict], client: anthropic.Anthropic) -> int:
    """Translate one chunk in place. Returns number of items actually changed."""
    to_translate = [
        {"id": item["id"], "title": item["title_en"], "summary": item["summary_en"]}
        for item in chunk
    ]
    prompt = TRANSLATE_PROMPT + json.dumps(to_translate, ensure_ascii=False)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    translations = json.loads(_strip_code_fence(response.content[0].text))
    return _apply_translations(chunk, translations)


def load_translation_cache(path: str) -> dict:
    """
    Load translations from the previous feed.json so unchanged items don't get
    re-translated on every run (the job runs several times a day). Returns a
    map of item id -> previous item dict. Missing/invalid file -> {}.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {it["id"]: it for it in data.get("items", []) if it.get("id")}
    except (OSError, ValueError, KeyError):
        return {}


def apply_cached_translations(items: list[dict], cache: dict) -> list[dict]:
    """
    Reuse a previous Spanish translation for any item whose id and English title
    are unchanged. Mutates matching items in place and returns the list of items
    that still need translating.
    """
    pending = []
    for item in items:
        prev = cache.get(item["id"])
        if (
            prev
            and prev.get("title_en") == item["title_en"]
            and prev.get("summary_en") == item["summary_en"]
            and prev.get("title_es")
        ):
            item["title_es"] = prev["title_es"]
            item["summary_es"] = prev.get("summary_es", item["summary_en"])
        else:
            pending.append(item)
    print(f"Reused {len(items) - len(pending)} cached translations; "
          f"{len(pending)} new to translate.")
    return pending


def translate_batch(items: list[dict], client: anthropic.Anthropic) -> list[dict]:
    """
    Translate titles and summaries to Spanish via Claude, in small chunks
    (better per-item fidelity than one big call) with English fallback on
    failure and a single targeted retry pass over anything left in English.
    """
    print("Translating to Spanish via Claude...")

    # English fallback up front; successful chunks overwrite it
    for item in items:
        item["title_es"] = item["title_en"]
        item["summary_es"] = item["summary_en"]

    CHUNK_SIZE = 8
    for start in range(0, len(items), CHUNK_SIZE):
        chunk = items[start:start + CHUNK_SIZE]
        try:
            _translate_chunk(chunk, client)
            print(f"  ✓ Translated {start + 1}–{start + len(chunk)}")
        except Exception as e:
            print(f"  ✗ Chunk {start + 1}–{start + len(chunk)} failed: {e}")

    # Targeted retry: re-translate items still identical to English (model
    # sometimes echoes terse headlines). Idempotent for true proper-noun items.
    leftovers = [i for i in items if i["title_es"] == i["title_en"]]
    if leftovers:
        print(f"  Retrying {len(leftovers)} items left in English...")
        for start in range(0, len(leftovers), CHUNK_SIZE):
            chunk = leftovers[start:start + CHUNK_SIZE]
            try:
                _translate_chunk(chunk, client)
            except Exception as e:
                print(f"  ✗ Retry chunk failed: {e}")

    translated = sum(1 for i in items if i["title_es"] != i["title_en"])
    print(f"  Translated {translated}/{len(items)} items")
    return items


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Fetch World Cup results first so they render as the top "Mundial" section.
    # Seasonal: set "world_cup_results": false in feeds.json once the tournament
    # is over so the dead API call is skipped.
    wc_items = fetch_world_cup_results() if CONFIG.get("world_cup_results", True) else []

    # Fetch RSS feeds
    items = fetch_all_feeds()

    items = wc_items + items

    if not items:
        print("No items fetched. Exiting.")
        return

    out_path = os.path.join(os.path.dirname(__file__), "feed.json")

    # Reuse translations from the previous run for unchanged items, then only
    # send genuinely new items to Claude.
    cache = load_translation_cache(out_path)
    pending = apply_cached_translations(items, cache)
    if pending:
        translate_batch(pending, client)
    else:
        print("All items already translated from cache — no Claude calls needed.")

    # Build output
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "item_count": len(items),
        "items": items,
    }

    # Write feed.json to repo root (where index.html lives)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Done. feed.json written with {len(items)} items.")


if __name__ == "__main__":
    main()
