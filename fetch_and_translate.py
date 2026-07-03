#!/usr/bin/env python3
"""
RSS Fetcher + Spanish Translator
Fetches RSS feeds, translates to Spanish via Claude API, outputs feed.json
"""

import json
import os
import re
import socket
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

# feedparser has no timeout parameter; without this a single unresponsive host
# hangs the whole scheduled run until the Actions job limit kills it.
socket.setdefaulttimeout(30)

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


def load_previous_feed() -> dict:
    """
    Map id -> item from the last committed feed.json (empty on first run or
    any read failure). Ids are stable (md5 of link), so unchanged items can
    reuse their existing translation instead of re-paying the API every run.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feed.json")
    try:
        with open(path, encoding="utf-8") as f:
            prev = json.load(f)
        return {i["id"]: i for i in prev.get("items", []) if "id" in i}
    except Exception:
        return {}


def dedupe_items(items: list[dict]) -> list[dict]:
    """
    Drop items whose id (md5 of link) was already seen, keeping the first
    occurrence. Overlapping feeds (e.g. the two Guardian/BBC football sources)
    can surface the same article twice; duplicate ids also collide in the
    frontend's data-id read-tracking.
    """
    seen: set[str] = set()
    unique = []
    for item in items:
        if item["id"] in seen:
            print(f"  – dropped duplicate: [{item['source']}] {item['title_en'][:60]}")
            continue
        seen.add(item["id"])
        unique.append(item)
    return unique


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


# Haiku 4.5 — short journalistic translation is squarely its use case, and it
# costs a third of Sonnet. Don't upgrade without measuring the quality gap.
TRANSLATE_MODEL = "claude-haiku-4-5"
CHUNK_SIZE = 8
BATCH_POLL_SECONDS = 10
BATCH_TIMEOUT_SECONDS = 600  # workflow job timeout is 15 min; leave headroom

# Haiku 4.5 $/Mtok as of 2026-07 (batch = 50%). Update if TRANSLATE_MODEL changes.
PRICE_IN, PRICE_OUT = 1.00, 5.00
# Token usage this run, so every Actions log shows real spend, not an estimate.
USAGE = {"batch_in": 0, "batch_out": 0, "direct_in": 0, "direct_out": 0}


def _count_usage(message, batched: bool):
    try:
        key = "batch" if batched else "direct"
        USAGE[key + "_in"] += message.usage.input_tokens
        USAGE[key + "_out"] += message.usage.output_tokens
    except Exception:
        pass  # telemetry must never break the build


def print_usage():
    cost = (USAGE["batch_in"] * PRICE_IN / 2 + USAGE["batch_out"] * PRICE_OUT / 2
            + USAGE["direct_in"] * PRICE_IN + USAGE["direct_out"] * PRICE_OUT) / 1e6
    tokens_in = USAGE["batch_in"] + USAGE["direct_in"]
    tokens_out = USAGE["batch_out"] + USAGE["direct_out"]
    print(f"API usage this run: {tokens_in} in / {tokens_out} out tokens "
          f"≈ ${cost:.4f} (≈ ${cost * 2 * 365:.2f}/year at 2 runs/day)")


def _build_prompt(chunk: list[dict]) -> str:
    to_translate = [
        {"id": item["id"], "title": item["title_en"], "summary": item["summary_en"]}
        for item in chunk
    ]
    return TRANSLATE_PROMPT + json.dumps(to_translate, ensure_ascii=False)


def _apply_translations(chunk: list[dict], raw: str) -> int:
    """
    Parse a model response and apply it to the chunk in place. Items that got
    a response entry are marked es_confirmed — for proper-noun headlines that
    legitimately stay identical to English, this is what stops them being
    re-sent to the API on every future run. Returns number of items changed.
    """
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    translations = json.loads(raw)
    # Match by id (coerced to str). The model sometimes returns the translated
    # text under the *input* key names ("title"/"summary") instead of the
    # requested "title_es"/"summary_es" — accept either, or fall back positionally.
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
        if title_es:
            item["es_confirmed"] = True
        if item["title_es"] != item["title_en"]:
            changed += 1
    return changed


def _translate_chunk(chunk: list[dict], client: anthropic.Anthropic) -> int:
    """Translate one chunk in place with a direct (synchronous) API call."""
    response = client.messages.create(
        model=TRANSLATE_MODEL,
        max_tokens=8000,
        messages=[{"role": "user", "content": _build_prompt(chunk)}],
    )
    _count_usage(response, batched=False)
    return _apply_translations(chunk, response.content[0].text)


def _translate_chunks_batched(chunks: list[list[dict]], client: anthropic.Anthropic) -> bool:
    """
    Translate all chunks through the Message Batches API (50% of standard
    price). Small batches normally finish in a couple of minutes; on timeout
    the unprocessed items simply keep their English fallback and are retried
    on the next scheduled run. Returns False if the batch could not even be
    submitted — the caller then falls back to direct calls.
    """
    try:
        batch = client.messages.batches.create(
            requests=[
                {
                    "custom_id": f"chunk-{i}",
                    "params": {
                        "model": TRANSLATE_MODEL,
                        "max_tokens": 8000,
                        "messages": [{"role": "user", "content": _build_prompt(c)}],
                    },
                }
                for i, c in enumerate(chunks)
            ]
        )
    except Exception as e:
        print(f"  Batch submit failed ({e}) — falling back to direct calls.")
        return False

    print(f"  Submitted batch {batch.id} ({len(chunks)} chunks); polling...")
    deadline = time.time() + BATCH_TIMEOUT_SECONDS
    while True:
        status = client.messages.batches.retrieve(batch.id)
        if status.processing_status == "ended":
            break
        if time.time() > deadline:
            print("  ✗ Batch timed out — publishing with fallbacks; next run retries.")
            try:
                client.messages.batches.cancel(batch.id)
            except Exception:
                pass
            return True
        time.sleep(BATCH_POLL_SECONDS)

    for result in client.messages.batches.results(batch.id):
        idx = int(result.custom_id.rsplit("-", 1)[1])
        if result.result.type != "succeeded":
            print(f"  ✗ Chunk {idx + 1} failed in batch: {result.result.type}")
            continue
        try:
            msg = result.result.message
            _count_usage(msg, batched=True)
            text = next(b.text for b in msg.content if b.type == "text")
            _apply_translations(chunks[idx], text)
        except Exception as e:
            print(f"  ✗ Chunk {idx + 1} unparseable: {e}")
    return True


def translate_batch(items: list[dict], client: anthropic.Anthropic) -> list[dict]:
    """
    Translate titles and summaries to Spanish via Claude — one Batches-API
    submission for all chunks (falling back to direct calls if batching is
    unavailable), English fallback per item on failure, and a targeted direct
    retry pass over anything left in English and unconfirmed.
    """
    print("Translating to Spanish via Claude...")

    # English fallback up front; successful chunks overwrite it
    for item in items:
        item["title_es"] = item["title_en"]
        item["summary_es"] = item["summary_en"]

    chunks = [items[i:i + CHUNK_SIZE] for i in range(0, len(items), CHUNK_SIZE)]
    if not _translate_chunks_batched(chunks, client):
        for i, chunk in enumerate(chunks):
            try:
                _translate_chunk(chunk, client)
                print(f"  ✓ Translated chunk {i + 1}/{len(chunks)}")
            except Exception as e:
                print(f"  ✗ Chunk {i + 1}/{len(chunks)} failed: {e}")

    # Targeted retry (direct calls — the volume is small): items still equal
    # to English whose chunk failed or whose entry went missing. Items the
    # model *returned* unchanged are es_confirmed and don't retry.
    leftovers = [
        i for i in items
        if i["title_es"] == i["title_en"] and not i.get("es_confirmed")
    ]
    if leftovers:
        print(f"  Retrying {len(leftovers)} unconfirmed items left in English...")
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

    # Fetch World Cup results first so they render as the top "Mundial" section
    wc_items = fetch_world_cup_results()

    # Fetch RSS feeds
    items = fetch_all_feeds()

    items = dedupe_items(wc_items + items)

    if not items:
        print("No items fetched. Exiting.")
        return

    # Reuse translations from the previous run for unchanged items. Reusable:
    # items whose Spanish differs from English (actually translated), or
    # es_confirmed items (a successful API call returned them unchanged —
    # legit proper-noun headlines). Unconfirmed English-identical items
    # (earlier failures) go back through the API.
    prev = load_previous_feed()
    to_translate = []
    for item in items:
        p = prev.get(item["id"])
        if (p and p.get("title_en") == item["title_en"]
                and p.get("summary_en") == item["summary_en"]
                and p.get("title_es")
                and (p["title_es"] != p["title_en"]
                     or p.get("summary_es") != p.get("summary_en")
                     or p.get("es_confirmed"))):
            item["title_es"] = p["title_es"]
            item["summary_es"] = p.get("summary_es") or item["summary_en"]
            if p.get("es_confirmed"):
                item["es_confirmed"] = True
        else:
            to_translate.append(item)

    reused = len(items) - len(to_translate)
    if reused:
        print(f"Reusing {reused} existing translations; {len(to_translate)} items need the API.")

    # Translate (World Cup results go through the same path as everything else)
    if to_translate:
        translate_batch(to_translate, client)
    else:
        print("Nothing new to translate.")
    print_usage()

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
