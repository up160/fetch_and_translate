# SEÑAL // Feed Diario

Daily RSS reader that fetches English-language news and translates to Spanish via Claude API. Hosted on GitHub Pages.

## Structure

```
├── fetch_and_translate.py   # Daily fetch + translate script
├── requirements.txt
├── feed.json                # Generated output (committed by CI)
├── index.html               # Static site
└── .github/
    └── workflows/
        └── daily.yml        # Scheduled GitHub Action
```

## Setup

### 1. Create GitHub repo & enable Pages

- Push this directory to a new GitHub repo
- Go to **Settings → Pages → Source**: set to `Deploy from branch`, branch `main`, folder `/root`
- Your site will be at `https://<your-username>.github.io/<repo-name>/`

### 2. Add your Anthropic API key

- Go to **Settings → Secrets and variables → Actions**
- Add a secret named `ANTHROPIC_API_KEY` with your key from console.anthropic.com

### 3. Generate initial feed.json

Run locally first to verify everything works:

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python fetch_and_translate.py
```

Commit the resulting `feed.json`, then push. The site will render immediately.

### 4. Let it run automatically

The GitHub Action runs daily at 07:00 UTC. You can also trigger it manually from the **Actions** tab → **Daily RSS Feed Update** → **Run workflow**.

## Feeds Included

| Category  | Source                   |
|-----------|--------------------------|
| Tech      | Hacker News, The Verge, Ars Technica |
| News      | BBC News, The Guardian   |
| Sport     | BBC Sport                |
| Football  | Liverpool FC (Sky Sports), Wales Football (BBC) |
| Rugby     | Wales Rugby (BBC)        |
| MMA       | MMA Junkie, Bloody Elbow |

## Customisation

- **Add/remove feeds**: edit the `FEEDS` list in `fetch_and_translate.py`
- **Change item count per feed**: edit `MAX_ITEMS_PER_FEED`
- **Change schedule**: edit the `cron` line in `.github/workflows/daily.yml`
- **Language toggle**: the site has an ES/EN toggle built in — EN shows original text

## Estimated Claude API cost

~50 items × ~150 tokens each = ~7,500 tokens/day translated  
At Sonnet pricing this is well under $0.05/day.
