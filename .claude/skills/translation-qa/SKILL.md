---
name: translation-qa
description: Spot-check Spanish translation quality in feed.json and safely tune the Claude translation prompt or chunking/retry logic in fetch_and_translate.py. Use when translations look wrong/literal/missing, when items show up in English on the site, or when asked to change the translation style, model, or prompt.
---

# Translation quality: check and tune

## Spot-checking the current output

```bash
python -c "
import json
d = json.load(open('feed.json'))
same = [i for i in d['items'] if i['title_es'] == i['title_en']]
print(f\"{len(d['items'])} items, {len(same)} with title_es == title_en:\")
for i in same: print(f\"  [{i['category']}] {i['title_en'][:80]}\")
"
```

Untranslated items are **not automatically bugs**: terse proper-noun headlines ("Wales 24–17 Scotland", "Bellingcat") legitimately survive translation unchanged. It's a problem when full English sentences appear — that means a chunk failed and the retry pass also failed. Check the last Actions run log for `✗ Chunk` lines.

To eyeball quality, print a few en/es pairs per category and judge: natural journalistic Spanish (Spain), proper nouns untranslated, numbers/scores/dates preserved, sports/tech loanwords kept where Spanish media keeps them (ransomware, hacker, try, scrum).

## Tuning the prompt (`TRANSLATE_PROMPT`)

- The prompt demands **ONLY a raw JSON array** with keys `id, title_es, summary_es`. Any prompt change must preserve that contract — the parser strips code fences but expects JSON.
- Known model quirk already handled downstream: translations sometimes come back under the *input* key names (`title`/`summary`); `_translate_chunk`'s `pick()` accepts both, with positional fallback. Don't remove that leniency.
- Style rules live in the prompt, not the code. Add style guidance as new bullet lines; keep the output-format paragraph last and intact.

## Testing prompt changes cheaply

Requires `ANTHROPIC_API_KEY`. Don't burn tokens re-running the whole pipeline — translate one small batch from the committed feed.json (script goes in the scratchpad):

```python
import json, anthropic, sys
sys.path.insert(0, "/home/user/fetch_and_translate")
from fetch_and_translate import _translate_chunk
items = json.load(open("/home/user/fetch_and_translate/feed.json"))["items"][:8]
for i in items: i["title_es"] = i["title_en"]; i["summary_es"] = i["summary_en"]
_translate_chunk(items, anthropic.Anthropic())
for i in items: print(f"EN: {i['title_en']}\nES: {i['title_es']}\n")
```

Pick a mixed batch (a score line, a tech headline, a long summary) rather than the first 8 if the change targets a specific failure. Compare before/after on the *same* items. If no API key is available in this session, make the prompt edit anyway, explain the reasoning, and tell the user to verify via a manual `workflow_dispatch` run.

## Invariants — do not break

- Per-item English fallback stays: every item must always have `title_es`/`summary_es`, even if every API call fails.
- A translation failure must never crash the pipeline (CI commits whatever was produced).
- `CHUNK_SIZE = 8` balances fidelity vs. calls; `max_tokens=8000` must comfortably fit a chunk — if you raise CHUNK_SIZE or SUMMARY_CAP, re-check that budget.
- The model is pinned (`claude-sonnet-4-6`) for cost (~50 items/day). Model changes are the user's call — if asked, check current model names/pricing via the claude-api skill rather than from memory.
