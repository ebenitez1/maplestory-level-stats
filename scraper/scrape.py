#!/usr/bin/env python3
"""Scrape Nexon GMS rankings and bucket counts by class & level threshold.

Output: ../data/stats.json
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

PAGE_CONCURRENCY = 8
CLASS_CONCURRENCY = 4
MAX_PAGES_PER_CLASS = 2000
STOP_AFTER_LOW_BATCHES = 2
RETRY_ATTEMPTS = 4
REQUEST_TIMEOUT_S = 30
USER_AGENT = "maplestory-level-stats/1.0 (+https://github.com/ebenitez1/maplestory-level-stats)"


async def fetch_page(session, job, page):
    params = {"type": "job", "id": job, "page_index": page}
    for attempt in range(RETRY_ATTEMPTS):
        try:
            async with session.get(API, params=params, timeout=REQUEST_TIMEOUT_S) as r:
                if r.status == 429:
                    await asyncio.sleep(2 ** attempt)
                    continue
                r.raise_for_status()
                data = await r.json()
                return data.get("ranks", [])
        except Exception as e:
            if attempt == RETRY_ATTEMPTS - 1:
                print(f"[{job} p{page}] gave up: {e}", file=sys.stderr)
                return []
            await asyncio.sleep(1 + attempt)
    return []


async def scrape_class(session, job):
    buckets = {str(t): 0 for t in THRESHOLDS}
    page = 1
    low_streak = 0
    seen = 0

    while page <= MAX_PAGES_PER_CLASS:
        batch = list(range(page, min(page + PAGE_CONCURRENCY, MAX_PAGES_PER_CLASS + 1)))
        results = await asyncio.gather(*[fetch_page(session, job, p) for p in batch])

        eligible = 0
        empty = 0
        for ranks in results:
            if not ranks:
                empty += 1
                continue
            for entry in ranks:
                seen += 1
                lvl = entry.get("level", 0)
                if lvl >= MIN_LEVEL:
                    eligible += 1
                    for t in THRESHOLDS:
                        if lvl >= t:
                            buckets[str(t)] += 1

        if empty == len(results):
            break
        if eligible == 0:
            low_streak += 1
            if low_streak >= STOP_AFTER_LOW_BATCHES:
                break
        else:
            low_streak = 0

        page += PAGE_CONCURRENCY
        await asyncio.sleep(0.2)

    print(f"[{job}] seen={seen} buckets={buckets}", file=sys.stderr)
    return buckets


async def main():
    timeout = aiohttp.ClientTimeout(total=60)
    conn = aiohttp.TCPConnector(limit=PAGE_CONCURRENCY * CLASS_CONCURRENCY)
    sem = asyncio.Semaphore(CLASS_CONCURRENCY)
    results = {}
    started = time.time()

    async with aiohttp.ClientSession(
        timeout=timeout, connector=conn, headers={"User-Agent": USER_AGENT}
    ) as session:
        async def run(job):
            async with sem:
                results[job] = await scrape_class(session, job)

        await asyncio.gather(*[run(c) for c in CLASSES])

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
