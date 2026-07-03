---
name: preview-site
description: Serve index.html locally and screenshot it with Playwright to verify frontend changes actually render — layout, category sections, ES/EN toggle, images, empty states. Use after any edit to index.html, or when asked "what does the site look like" / "check the frontend".
---

# Preview and verify the site

The frontend is one self-contained file (`index.html`) that fetches `./feed.json` client-side. It cannot be verified by reading the code — serve it and look at it.

## Serve + screenshot

```bash
cd /home/user/fetch_and_translate && python -m http.server 8123 &
```

Then screenshot with the pre-installed Chromium (write scripts to the scratchpad, not the repo):

```js
// screenshot.mjs — run with: node screenshot.mjs
import { chromium } from 'playwright';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [];
page.on('console', m => m.type() === 'error' && errors.push(m.text()));
page.on('pageerror', e => errors.push(String(e)));
await page.goto('http://localhost:8123/', { waitUntil: 'networkidle' });
await page.screenshot({ path: 'site-desktop.png', fullPage: false });
await page.setViewportSize({ width: 390, height: 844 });   // mobile
await page.screenshot({ path: 'site-mobile.png', fullPage: false });
if (errors.length) console.log('CONSOLE ERRORS:\n' + errors.join('\n'));
await browser.close();
```

If `playwright` isn't installed in the scratchpad: `npm init -y && npm i playwright` there (browsers are pre-installed at `/opt/pw-browsers`; never run `playwright install`).

**Read the screenshots** with the Read tool and actually check them, then send them to the user with SendUserFile. Kill the server when done.

## What to verify per change type

- **Any change**: zero console errors; header, category nav and item cards render; Google Fonts may be blocked by the sandbox proxy — a fallback font is fine, but note it.
- **Layout/CSS**: both desktop (1280px) and mobile (390px) screenshots.
- **ES/EN toggle**: click it (`page.click(...)`) and screenshot both states — titles must switch between `title_es` and `title_en`.
- **Feed rendering logic**: also test the failure path — temporarily serve from a dir without `feed.json` and confirm the error state renders (`ERROR: No se pudo cargar feed.json`), not a blank page.
- **New category added**: confirm it appears in the nav and its section renders (may need a hand-built test feed.json in the scratchpad if CI hasn't picked it up yet — point the fetch at it by serving from scratchpad with a copied index.html, don't edit the repo's feed.json).

## Constraints

- No build step, no frameworks, no external JS files — everything stays inline in `index.html` and must work as plain static files on GitHub Pages.
- `feed.json` is loaded with a cache-busting query (`?t=` + timestamp); keep that when touching the fetch code.
- UI copy is Spanish (Spain). New user-facing strings should match the existing register.
