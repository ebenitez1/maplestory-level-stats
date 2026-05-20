#!/usr/bin/env python3
"""Scrape Nexon GMS rankings and bucket counts by class & level threshold.

Output: ../data/stats.json

The Nexon rankings API is paginated at 10 entries per page, sorted by exp
descending. We walk each class until we hit characters below the minimum
threshold (270 by default).

Rate-limiting notes:
- Nexon silently returns empty `ranks` arrays (with HTTP 200) when
  rate-limited, NOT HTTP 429. We use the `totalCount` field to detect this:
  if we get an empty page but haven't seen the full character count yet, we
  back off and retry.
- Concurrency is intentionally modest (one class at a time, ~10 pages in
  flight) to stay below whatever undisclosed rate threshold Nexon enforces.
"""

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

API = "https://www.nexon.com/api/maplestory/no-auth/ranking/v2/na"
THRESHOLDS = [270, 275, 280, 285, 290, 295, 300]
MIN_LEVEL = THRESHOLDS[0]

CLASSES = [
    "Adele", "Angelic Buster", "Aran",
    "Arch Mage (F/P)", "Arch Mage (I/L)",
    "Ark", "Battle Mage", "Beginner", "Bishop", "Blade Master",
    "Blaster", "Blaze Wizard", "Bow Master", "Buccaneer", "Cadena",
    "Cannoneer", "Corsair", "Dark Knight", "Dawn Warrior", "Demon Avenger",
    "Demon Slayer", "Dual Blade", "Evan", "Hayato", "Hero",
    "Hoyoung", "Illium", "Kain", "Kaiser", "Kanna",
    "Khali", "Kinesis", "Lara", "Luminous", "Marksman",
    "Mechanic", "Mercedes", "Mihile", "Night Lord", "Night Walker",
    "Paladin", "Pathfinder", "Phantom", "Shade", "Shadower",
    "Thunder Breaker", "Wild Hunter", "Wind Archer", "Xenon", "Zero",
]

PAGE_CONCURRENCY = 10
MAX_PAGES_PER_CLASS = 3000
BATCH_SLEEP_S = 0.5
RATE_LIMIT_BACKOFF_S = 30
SUSPICIOUS_RETRIES = 3
RETRY_ATTEMPTS = 6
REQUEST_TIMEOUT_S = 30
USER_AGENT = "maplestory-level-stats/1.0 (+https://github.com/ebenitez1/maplestory-level-stats)"


async def fetch(session, job, page):
    """Fetch one page. Returns (ranks, total_count). ranks=None means hard failure."""
    params = {"type": "job", "id": job, "page_index": page}
    last_err = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            async with session.get(API, params=params, timeout=REQUEST_TIMEOUT_S) as r:
                if r.status == 429:
                    wait = min(RATE_LIMIT_BACKOFF_S * (attempt + 1), 300)
                    print(f"  [{job} p{page}] HTTP 429, sleeping {wait}s", file=sys.stderr)
                    await asyncio.sleep(wait)
                    continue
                r.raise_for_status()
                data = await r.json()
                return data.get("ranks", []), data.get("totalCount")
        except Exception as e:
            last_err = e
            await asyncio.sleep(2 ** attempt)
    print(f"  [{job} p{page}] gave up: {last_err}", file=sys.stderr)
    return None, None


async def scrape_class(session, job):
    buckets = {str(t): 0 for t in THRESHOLDS}
    page = 1
    seen = 0
    total_count = None
    suspicious_retries = 0

    while page <= MAX_PAGES_PER_CLASS:
        batch_pages = list(range(page, min(page + PAGE_CONCURRENCY, MAX_PAGES_PER_CLASS + 1)))
        results = await asyncio.gather(*[fetch(session, job, p) for p in batch_pages])

        any_data = False
        any_eligible = False
        for ranks, total in results:
            if total is not None and total_count is None:
                total_count = total
                if total == 0:
                    print(f"[{job}] totalCount=0 — class name probably wrong", file=sys.stderr)
                    return buckets
            if not ranks:
                continue
            any_data = True
            for entry in ranks:
                seen += 1
                lvl = entry.get("level", 0)
                if lvl >= MIN_LEVEL:
                    any_eligible = True
                    for t in THRESHOLDS:
                        if lvl >= t:
                            buckets[str(t)] += 1

        if not any_data:
            # Empty pages: rate limit or end of data?
            if total_count is not None and seen < total_count and suspicious_retries < SUSPICIOUS_RETRIES:
                suspicious_retries += 1
                wait = RATE_LIMIT_BACKOFF_S * suspicious_retries
                print(
                    f"  [{job}] empty at p{page} (seen {seen}/{total_count}), "
                    f"backoff {wait}s (retry {suspicious_retries}/{SUSPICIOUS_RETRIES})",
                    file=sys.stderr,
                )
                await asyncio.sleep(wait)
                continue  # retry same batch
            break

        suspicious_retries = 0

        if not any_eligible:
            # All characters in this batch are below MIN_LEVEL — we're past the threshold
            print(f"[{job}] all below {MIN_LEVEL} at p{page}, done", file=sys.stderr)
            break

        page += PAGE_CONCURRENCY
        await asyncio.sleep(BATCH_SLEEP_S)

    print(f"[{job}] seen={seen}/{total_count} buckets={buckets}", file=sys.stderr)
    return buckets


async def main():
    timeout = aiohttp.ClientTimeout(total=60)
    conn = aiohttp.TCPConnector(limit=PAGE_CONCURRENCY)
    results = {}
    started = time.time()

    async with aiohttp.ClientSession(
        timeout=timeout, connector=conn, headers={"User-Agent": USER_AGENT}
    ) as session:
        for job in CLASSES:
            results[job] = await scrape_class(session, job)

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "region": "GMS (North America)",
        "thresholds": THRESHOLDS,
        "min_level": MIN_LEVEL,
        "classes": {k: results[k] for k in sorted(results)},
        "duration_seconds": round(time.time() - started, 1),
    }
    out_path = Path(__file__).resolve().parent.parent / "data" / "stats.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {out_path} in {out['duration_seconds']}s", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
