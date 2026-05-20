# MapleStory GMS Level Stats

Counts of ranked GMS (Global MapleStory / North America) characters at each level threshold — 270+, 275+, 280+, 285+, 290+, 295+, 300 — broken down by class. Inspired by the now-defunct maplestory.gg statistics page.

**Live page:** https://ebenitez1.github.io/maplestory-level-stats/

## How it works

Nexon's rankings API (`https://www.nexon.com/api/maplestory/no-auth/ranking/v2/na?type=job&id=<ClassName>&page_index=<N>`) returns 10 entries per page, sorted by exp descending. Two important quirks:

1. **No 429.** When you exceed Nexon's rate limit they return **HTTP 403 Forbidden** as a persistent per-IP block (triggers around ~800 successful requests).
2. **Silent empties.** Below the rate-limit threshold they sometimes return HTTP 200 with an empty `ranks` array; we use the `totalCount` field to tell that apart from actual end-of-data.

To work around the per-IP block, the scraper runs as a **matrix workflow**: one GitHub Actions job per class, each on its own runner (its own IP). Each job:

1. Calls `scrape.py --class "<ClassName>"`, which walks pages until it hits characters below level 270 (or 1000 pages, whichever comes first).
2. Writes its result to `data/partials/<ClassName>.json`.
3. Uploads it as an artifact.

A final `combine` job downloads all partials, merges them into `data/stats.json`, and commits.

The static page (`index.html` + `app.js`) loads `data/stats.json` and renders the table.

## One-time setup

1. **Add the workflow file.** Create `.github/workflows/scrape.yml` and paste the YAML at the bottom of this README. (The GitHub MCP token can't write workflow files for security reasons.)
2. **Enable Pages.** Settings → Pages → Source = *Deploy from a branch* → Branch = `main` → Folder = `/ (root)`. Save.
3. **Allow the Action to commit.** Settings → Actions → General → Workflow permissions = *Read and write permissions*. Save.
4. **Trigger a run.** Actions → Scrape rankings → Run workflow.

Wall-clock for a full run: ~15–25 min (8 classes in parallel, ~50 classes total). Each individual class scrape takes 1–5 min depending on how many characters it has at 270+.

## Local development

```bash
pip install -r scraper/requirements.txt

# scrape one class (writes data/partials/Bishop.json)
python scraper/scrape.py --class "Bishop"

# scrape all sequentially (slow, will hit the IP block around the 800th request — partial data is OK for local testing)
python scraper/scrape.py

# combine partials -> data/stats.json
python scraper/combine.py

# serve the page
python -m http.server  # http://localhost:8000
```

## Tuning

Edit `scraper/scrape.py`:
- `THRESHOLDS` — level buckets shown.
- `CLASSES` — list of `jobName` values to scrape. If a class returns 0 unexpectedly the name probably doesn't match what Nexon returns; try `curl "https://www.nexon.com/api/maplestory/no-auth/ranking/v2/na?type=job&id=YourGuess&page_index=1"` and inspect `totalCount`.
- `PAGE_CONCURRENCY` / `BATCH_SLEEP_S` — raise for speed, lower if jobs hit 403 early.
- `MAX_PAGES_PER_CLASS` — safety cap. 1000 pages = 10k characters, comfortably under the observed per-IP block. Raise carefully.

Edit `.github/workflows/scrape.yml`:
- `cron` — schedule (default weekly Sunday 06:00 UTC).
- `max-parallel` — how many classes run concurrently. 8 is reasonable; higher risks overlapping runner IPs.

## Caveats

- Counts characters, not unique players (one player can have many).
- Only includes characters in public rankings.
- A class showing `status: "blocked"` in `data/stats.json` was cut short by 403 — its counts are a lower bound.
- A class showing 0s with no status entry usually means the name in `CLASSES` doesn't match Nexon's `jobName`.

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
  list-classes:
    runs-on: ubuntu-latest
    outputs:
      classes: ${{ steps.set.outputs.classes }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - id: set
        run: echo "classes=$(python scraper/scrape.py --list)" >> "$GITHUB_OUTPUT"

  scrape:
    needs: list-classes
    runs-on: ubuntu-latest
    timeout-minutes: 30
    strategy:
      max-parallel: 8
      fail-fast: false
      matrix:
        class: ${{ fromJson(needs.list-classes.outputs.classes) }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: scraper/requirements.txt
      - run: pip install -r scraper/requirements.txt
      - run: python scraper/scrape.py --class "${{ matrix.class }}"
      - uses: actions/upload-artifact@v4
        with:
          name: partial-${{ strategy.job-index }}
          path: data/partials/
          retention-days: 1
          if-no-files-found: warn

  combine:
    needs: scrape
    if: always()
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: actions/download-artifact@v4
        with:
          path: data/partials/
          pattern: partial-*
          merge-multiple: true
      - run: python scraper/combine.py
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
