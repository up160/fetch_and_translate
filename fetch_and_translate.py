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
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from typing import Callable, Optional

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

# ─── Translation backend selection ──────────────────────────────────────────
# TRANSLATE_BACKEND:
#   "auto"   (default) — use Ollama if OLLAMA_HOST is set, otherwise Claude.
#                        Whichever is primary, the other is used as fallback.
#   "ollama"           — Ollama primary (defaults to localhost), Claude fallback.
#   "claude"           — Claude only (original behaviour).
# This keeps the existing GitHub Actions run unchanged (no OLLAMA_HOST -> Claude),
# while letting the home-server M1 run translation locally for free by setting
# TRANSLATE_BACKEND=ollama (or pointing OLLAMA_HOST at the box).
TRANSLATE_BACKEND = os.environ.get("TRANSLATE_BACKEND", "auto").lower().strip()
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "").strip()
# qwen2.5:7b-instruct is a strong, fast multilingual default that fits an M1/16GB
# at Q4 (~5GB). For higher Spanish fidelity bump to qwen2.5:14b-instruct or
# aya-expanse:8b (Cohere's translation-tuned model) — see README.
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "180"))
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

OLLAMA_ENABLED = TRANSLATE_BACKEND == "ollama" or (
    TRANSLATE_BACKEND == "auto" and bool(OLLAMA_HOST)
)


def _ollama_base() -> str:
    return (OLLAMA_HOST or "http://localhost:11434").rstrip("/")


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


# A "completer" is any callable that takes a prompt string and returns the
# model's raw text response. This lets the chunk translator stay agnostic about
# whether the text came from Ollama or Claude.
Completer = Callable[[str], str]


def _claude_completer(client: anthropic.Anthropic) -> Completer:
    def complete(prompt: str) -> str:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    return complete


def _ollama_completer() -> Completer:
    url = _ollama_base() + "/api/chat"

    def complete(prompt: str) -> str:
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            # Low temperature keeps translations faithful; format=json nudges
            # local models to emit parseable output instead of prose.
            "format": "json",
            "options": {"temperature": 0.2},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["message"]["content"]
    return complete


def _chained_completer(providers: list[tuple[str, Completer]]) -> Completer:
    """
    Try each backend in order; the first that returns without raising wins.
    A failing primary (e.g. Ollama down, or Claude out of credits) silently
    falls through to the next, so translation degrades gracefully.
    """
    def complete(prompt: str) -> str:
        last_err: Optional[Exception] = None
        for name, fn in providers:
            try:
                return fn(prompt)
            except Exception as e:  # noqa: BLE001 — any backend failure -> try next
                last_err = e
                print(f"    ! {name} backend failed ({e}); trying next backend")
        raise last_err or RuntimeError("no translation backend configured")
    return complete


def build_completer() -> tuple[Optional[Completer], list[str]]:
    """
    Assemble the ordered list of translation backends from configuration.
    Returns (completer, backend_names). completer is None if none are available.
    """
    providers: list[tuple[str, Completer]] = []

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

    if TRANSLATE_BACKEND == "claude":
        if client:
            providers.append(("claude", _claude_completer(client)))
    elif TRANSLATE_BACKEND == "ollama":
        providers.append(("ollama", _ollama_completer()))
        if client:
            providers.append(("claude", _claude_completer(client)))
    else:  # "auto"
        if OLLAMA_ENABLED:
            providers.append(("ollama", _ollama_completer()))
        if client:
            providers.append(("claude", _claude_completer(client)))

    if not providers:
        return None, []
    return _chained_completer(providers), [name for name, _ in providers]


def _parse_translations(raw: str) -> list:
    """
    Pull a JSON array of translation objects out of a model response, tolerating
    code fences and (from format=json local models) an object wrapper like
    {"items": [...]} or {"translations": [...]}.
    """
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Last resort: grab the outermost [...] span.
        start, end = raw.find("["), raw.rfind("]")
        if start != -1 and end > start:
            data = json.loads(raw[start:end + 1])
        else:
            raise

    if isinstance(data, dict):
        # Unwrap the first list-valued key, else treat the dict as a single item.
        for value in data.values():
            if isinstance(value, list):
                return value
        return [data]
    return data


def _translate_chunk(chunk: list[dict], complete: Completer) -> int:
    """Translate one chunk in place. Returns number of items actually changed."""
    to_translate = [
        {"id": item["id"], "title": item["title_en"], "summary": item["summary_en"]}
        for item in chunk
    ]
    prompt = TRANSLATE_PROMPT + json.dumps(to_translate, ensure_ascii=False)

    raw = complete(prompt)
    translations = _parse_translations(raw)
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
        if item["title_es"] != item["title_en"]:
            changed += 1
    return changed


def translate_batch(items: list[dict], complete: Completer) -> list[dict]:
    """
    Translate titles and summaries to Spanish, in small chunks (better per-item
    fidelity than one big call) with English fallback on failure and a single
    targeted retry pass over anything left in English. The `complete` callable
    abstracts the backend (Ollama and/or Claude with graceful fallback).
    """
    print("Translating to Spanish...")

    # English fallback up front; successful chunks overwrite it
    for item in items:
        item["title_es"] = item["title_en"]
        item["summary_es"] = item["summary_en"]

    CHUNK_SIZE = 8
    for start in range(0, len(items), CHUNK_SIZE):
        chunk = items[start:start + CHUNK_SIZE]
        try:
            _translate_chunk(chunk, complete)
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
                _translate_chunk(chunk, complete)
            except Exception as e:
                print(f"  ✗ Retry chunk failed: {e}")

    translated = sum(1 for i in items if i["title_es"] != i["title_en"])
    print(f"  Translated {translated}/{len(items)} items")
    return items


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    complete, backends = build_completer()
    if complete is None:
        raise ValueError(
            "No translation backend available. Set ANTHROPIC_API_KEY, or configure "
            "Ollama (TRANSLATE_BACKEND=ollama, or OLLAMA_HOST=http://host:11434)."
        )
    print(f"Translation backends (in order): {', '.join(backends)}")

    # Fetch World Cup results first so they render as the top "Mundial" section
    wc_items = fetch_world_cup_results()

    # Fetch RSS feeds
    items = fetch_all_feeds()

    items = wc_items + items

    if not items:
        print("No items fetched. Exiting.")
        return

    # Translate (World Cup results go through the same path as everything else)
    items = translate_batch(items, complete)

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
