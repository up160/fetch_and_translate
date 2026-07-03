"""Unit tests for the pure (no-network) logic in fetch_and_translate.py."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fetch_and_translate as m  # noqa: E402


# ─── extract_image ──────────────────────────────────────────────────────────

def test_extract_image_media_content():
    entry = {"media_content": [{"url": "http://x/img.jpg", "medium": "image"}]}
    assert m.extract_image(entry, "") == "http://x/img.jpg"


def test_extract_image_skips_non_image_media_content():
    # YouTube exposes the video itself as media:content (medium="video").
    entry = {
        "media_content": [{"url": "http://x/video.mp4", "medium": "video"}],
        "media_thumbnail": [{"url": "http://x/thumb.jpg"}],
    }
    assert m.extract_image(entry, "") == "http://x/thumb.jpg"


def test_extract_image_enclosure():
    entry = {"links": [{"rel": "enclosure", "type": "image/png", "href": "http://x/e.png"}]}
    assert m.extract_image(entry, "") == "http://x/e.png"


def test_extract_image_og_image_in_html():
    html = '<meta property="og:image" content="http://x/og.jpg">'
    assert m.extract_image({}, html) == "http://x/og.jpg"


def test_extract_image_img_tag_fallback():
    assert m.extract_image({}, '<p><img src="http://x/inline.jpg"></p>') == "http://x/inline.jpg"


def test_extract_image_none():
    assert m.extract_image({}, "no images here") == ""


# ─── _strip_code_fence ──────────────────────────────────────────────────────

def test_strip_code_fence_json():
    assert m._strip_code_fence("```json\n[1,2]\n```") == "[1,2]"


def test_strip_code_fence_plain():
    assert m._strip_code_fence("```\n[1]\n```") == "[1]"


def test_strip_code_fence_no_fence():
    assert m._strip_code_fence("  [1]  ") == "[1]"


# ─── _apply_translations ────────────────────────────────────────────────────

def test_apply_translations_by_id():
    chunk = [{"id": "1", "title_en": "A", "summary_en": "a"}]
    changed = m._apply_translations(chunk, [{"id": "1", "title_es": "AA", "summary_es": "aa"}])
    assert chunk[0]["title_es"] == "AA"
    assert chunk[0]["summary_es"] == "aa"
    assert changed == 1


def test_apply_translations_accepts_input_key_names():
    # Model sometimes echoes the input keys ("title"/"summary").
    chunk = [{"id": "1", "title_en": "A", "summary_en": "a"}]
    m._apply_translations(chunk, [{"id": "1", "title": "AA", "summary": "aa"}])
    assert chunk[0]["title_es"] == "AA"


def test_apply_translations_positional_fallback():
    chunk = [{"id": "1", "title_en": "A", "summary_en": "a"}]
    # id doesn't match -> falls back to positional
    m._apply_translations(chunk, [{"id": "999", "title_es": "AA", "summary_es": "aa"}])
    assert chunk[0]["title_es"] == "AA"


def test_apply_translations_falls_back_to_english_when_missing():
    chunk = [{"id": "1", "title_en": "Keep", "summary_en": "kept"}]
    m._apply_translations(chunk, [])
    assert chunk[0]["title_es"] == "Keep"
    assert chunk[0]["summary_es"] == "kept"


# ─── translation cache ──────────────────────────────────────────────────────

def test_apply_cached_translations_reuses_unchanged():
    cache = {"a": {"id": "a", "title_en": "Hi", "summary_en": "S",
                   "title_es": "Hola", "summary_es": "Ese"}}
    items = [{"id": "a", "title_en": "Hi", "summary_en": "S"}]
    pending = m.apply_cached_translations(items, cache)
    assert pending == []
    assert items[0]["title_es"] == "Hola"


def test_apply_cached_translations_retranslates_changed_title():
    cache = {"a": {"id": "a", "title_en": "Old", "summary_en": "S",
                   "title_es": "Viejo", "summary_es": "Ese"}}
    items = [{"id": "a", "title_en": "New", "summary_en": "S"}]
    pending = m.apply_cached_translations(items, cache)
    assert [p["id"] for p in pending] == ["a"]


def test_apply_cached_translations_new_item_pending():
    items = [{"id": "z", "title_en": "Brand new", "summary_en": "S"}]
    pending = m.apply_cached_translations(items, {})
    assert [p["id"] for p in pending] == ["z"]


def test_load_translation_cache_missing_file_returns_empty():
    assert m.load_translation_cache("/nonexistent/feed.json") == {}


# ─── es_confirmed: confirmed-identical vs failure fallback ──────────────────

def test_apply_translations_marks_returned_items_confirmed():
    # A successful response that echoes the title (proper noun) confirms it.
    chunk = [{"id": "1", "title_en": "Bellingcat", "summary_en": ""}]
    m._apply_translations(chunk, [{"id": "1", "title_es": "Bellingcat", "summary_es": ""}])
    assert chunk[0]["title_es"] == "Bellingcat"
    assert chunk[0].get("es_confirmed") is True


def test_apply_translations_missing_entry_not_confirmed():
    chunk = [{"id": "1", "title_en": "Keep", "summary_en": "kept"}]
    m._apply_translations(chunk, [])
    assert not chunk[0].get("es_confirmed")


def test_apply_cached_translations_reuses_confirmed_identical():
    cache = {"a": {"id": "a", "title_en": "Bellingcat", "summary_en": "",
                   "title_es": "Bellingcat", "summary_es": "", "es_confirmed": True}}
    items = [{"id": "a", "title_en": "Bellingcat", "summary_en": ""}]
    pending = m.apply_cached_translations(items, cache)
    assert pending == []
    assert items[0].get("es_confirmed") is True


def test_apply_cached_translations_retries_unconfirmed_english():
    # English-identical WITHOUT es_confirmed = fallback from a failed run.
    # It must stay pending, or a broken run would freeze the site in English.
    cache = {"a": {"id": "a", "title_en": "Some headline", "summary_en": "S",
                   "title_es": "Some headline", "summary_es": "S"}}
    items = [{"id": "a", "title_en": "Some headline", "summary_en": "S"}]
    pending = m.apply_cached_translations(items, cache)
    assert [p["id"] for p in pending] == ["a"]


# ─── dedupe_items ────────────────────────────────────────────────────────────

def test_dedupe_items_keeps_first_occurrence():
    items = [
        {"id": "x", "source": "A", "title_en": "Story"},
        {"id": "x", "source": "B", "title_en": "Story"},
        {"id": "y", "source": "A", "title_en": "Other"},
    ]
    out = m.dedupe_items(items)
    assert [i["id"] for i in out] == ["x", "y"]
    assert out[0]["source"] == "A"
