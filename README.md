# MapleStory GMS Level Stats

Counts of ranked GMS (Global MapleStory / North America) characters at each level threshold — 270+, 275+, 280+, 285+, 290+, 295+, 300 — broken down by class. Inspired by the now-defunct maplestory.gg statistics page.

**Live page:** https://ebenitez1.github.io/maplestory-level-stats/ *(after enabling Pages — see setup below)*

## How it works

- A GitHub Action (`.github/workflows/scrape.yml`) runs on a schedule (weekly by default).
- It hits Nexon's public rankings API: `https://www.nexon.com/api/maplestory/no-auth/ranking/v2/na?type=job&id=<ClassName>&page_index=<N>`.
- For each class, it walks the rankings until it stops finding characters at or above level 270.
- Counts are bucketed and written to `data/stats.json`.
- A static page (`index.html` + `app.js`) loads that JSON and renders the table.

## One-time setup after cloning

1. **Add the workflow file.** Create `.github/workflows/scrape.yml` (the GitHub MCP token can't write workflow files for security reasons). Paste the contents from `scraper/workflow.yml.template` in this repo, or use the snippet at the bottom of this README.
2. **Enable Pages.** Repo → Settings → Pages → Source = *Deploy from a branch*, Branch = `main`, Folder = `/ (root)`. Save.
3. **Allow the Action to push.** Repo → Settings → Actions → General → Workflow permissions = *Read and write permissions*. Save.
4. **Run the first scrape.** Repo → Actions → Scrape rankings → Run workflow.

First scrape takes ~15–40 minutes depending on how many high-level characters exist. After it commits `data/stats.json`, the page populates.

## Local development

```bash
pip install -r scraper/requirements.txt
python scraper/scrape.py
python -m http.server  # then visit http://localhost:8000
```

## Tuning

Edit `scraper/scrape.py`:
- `THRESHOLDS` — level buckets shown.
- `CLASSES` — list of `jobName` values to scrape. If a class returns 0 unexpectedly, the name probably doesn't match what Nexon returns; check a sample API call.
- `PAGE_CONCURRENCY` / `CLASS_CONCURRENCY` — raise for speed, lower if you hit 429s.
- `MAX_PAGES_PER_CLASS` — safety cap (default 2000 pages = 20k characters per class).

Change the schedule in `.github/workflows/scrape.yml` (cron line). Default is weekly Sunday 06:00 UTC.

## Caveats

- Counts characters, not unique players.
- Only includes characters that appear in public rankings.
- Data freshness depends on Nexon's ranking update cadence.
- If a class name in `CLASSES` doesn't match a Nexon `jobName` exactly, that row shows 0.

## Workflow YAML (paste into `.github/workflows/scrape.yml`)

```yaml
name: Scrape rankings

on:
  schedule:
    - cron: "0 6 * * 0"
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: scrape
  cancel-in-progress: false

jobs:
  scrape:
    runs-on: ubuntu-latest
    timeout-minutes: 120
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: scraper/requirements.txt
      - run: pip install -r scraper/requirements.txt
      - run: python scraper/scrape.py
      - name: Commit and push if changed
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          if [[ -n $(git status --porcelain data/stats.json) ]]; then
            git add data/stats.json
            git commit -m "Update stats $(date -u +%Y-%m-%d)"
            git push
          else
            echo "No changes to stats.json."
          fi
```
