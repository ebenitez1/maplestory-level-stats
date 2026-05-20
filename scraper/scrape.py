#!/usr/bin/env python3
"""Scrape Nexon GMS rankings and bucket counts by class & level threshold.

Modes:
  python scrape.py                  # all classes -> data/stats.json (slow, hits IP block)
  python scrape.py --class "Bishop" # one class  -> data/partials/Bishop.json (matrix mode)
  python scrape.py --list           # print CLASSES as JSON (consumed by workflow)

The Nexon API enforces a per-IP rate limit by returning HTTP 403 after roughly
800 successful requests. The recommended runtime is the matrix workflow which
spreads classes across separate runners (separate IPs).
"""

import argparse
import asyncio
import json
import re
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

PAGE_CONCURRENCY = 5
MAX_PAGES_PER_CLASS = 1000
BATCH_SLEEP_S = 0.5
REQUEST_TIMEOUT_S = 30
RETRY_ATTEMPTS_TRANSIENT = 4
USER_AGENT = "maplestory-level-stats/1.0 (+https://github.com/ebenitez1/maplestory-level-stats)"


class HardBlock(Exception):
    """Nexon returned 403; IP is blocked for some window."""


async def fetch(session, job, page):
    """Returns (ranks, total_count). Raises HardBlock on 403. (None, None) on other failure."""
    params = {"type": "job", "id": job, "page_index": page}
    last_err = None
    for attempt in range(RETRY_ATTEMPTS_TRANSIENT):
        try:
            async with session.get(API, params=params, timeout=REQUEST_TIMEOUT_S) as r:
                if r.status == 403:
                    raise HardBlock(f"403 at p{page}")
                if r.status == 429:
                    await asyncio.sleep(min(30 * (attempt + 1), 120))
                    continue
                r.raise_for_status()
                data = await r.json()
                return data.get("ranks", []), data.get("totalCount")
        except HardBlock:
            raise
        except Exception as e:
            last_err = e
            await asyncio.sleep(2 ** attempt)
    print(f"  [{job} p{page}] transient failure, giving up: {last_err}", file=sys.stderr)
    return None, None


async def scrape_class(session, job):
    buckets = {str(t): 0 for t in THRESHOLDS}
    page = 1
    seen = 0
    total_count = None
    status = "complete"

    while page <= MAX_PAGES_PER_CLASS:
        batch_pages = list(range(page, min(page + PAGE_CONCURRENCY, MAX_PAGES_PER_CLASS + 1)))
        try:
            results = await asyncio.gather(*[fetch(session, job, p) for p in batch_pages])
        except HardBlock as e:
            print(f"[{job}] HARD BLOCK (403) at p{page}: {e}", file=sys.stderr)
            status = "blocked"
            break

        any_data = False
        any_eligible = False
        for ranks, total in results:
            if total is not None and total_count is None:
                total_count = total
                if total == 0:
                    status = "no_data"
                    return buckets, seen, total_count, status, page
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
            if total_count is not None and seen >= total_count:
                break
            print(f"[{job}] persistent empty at p{page}, treating as end", file=sys.stderr)
            break

        if not any_eligible:
            break  # past MIN_LEVEL

        page += PAGE_CONCURRENCY
        await asyncio.sleep(BATCH_SLEEP_S)
    else:
        status = "max_pages_reached"

    print(f"[{job}] {status}: seen={seen}/{total_count} buckets={buckets}", file=sys.stderr)
    return buckets, seen, total_count, status, page


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


async def scrape_one(class_name: str):
    timeout = aiohttp.ClientTimeout(total=60)
    conn = aiohttp.TCPConnector(limit=PAGE_CONCURRENCY)
    started = time.time()
    async with aiohttp.ClientSession(
        timeout=timeout, connector=conn, headers={"User-Agent": USER_AGENT}
    ) as session:
        buckets, seen, total, status, stopped_at = await scrape_class(session, class_name)

    out = {
        "class": class_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "thresholds": THRESHOLDS,
        "min_level": MIN_LEVEL,
        "buckets": buckets,
        "seen": seen,
        "total_count": total,
        "status": status,
        "stopped_at_page": stopped_at,
        "duration_seconds": round(time.time() - started, 1),
    }
    out_path = Path(__file__).resolve().parent.parent / "data" / "partials" / f"{safe_filename(class_name)}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {out_path} in {out['duration_seconds']}s", file=sys.stderr)


async def scrape_all():
    timeout = aiohttp.ClientTimeout(total=60)
    conn = aiohttp.TCPConnector(limit=PAGE_CONCURRENCY)
    results = {}
    started = time.time()
    async with aiohttp.ClientSession(
        timeout=timeout, connector=conn, headers={"User-Agent": USER_AGENT}
    ) as session:
        for job in CLASSES:
            buckets, _, _, status, _ = await scrape_class(session, job)
            results[job] = buckets
            if status == "blocked":
                print(f"[{job}] aborting remaining classes due to IP block", file=sys.stderr)
                break

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "region": "GMS (North America)",
        "thresholds": THRESHOLDS,
        "min_level": MIN_LEVEL,
        "classes": {k: results.get(k, {str(t): 0 for t in THRESHOLDS}) for k in CLASSES},
        "duration_seconds": round(time.time() - started, 1),
    }
    out_path = Path(__file__).resolve().parent.parent / "data" / "stats.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {out_path} in {out['duration_seconds']}s", file=sys.stderr)


def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument("--class", dest="class_name", help="Scrape one class to data/partials/")
    g.add_argument("--list", action="store_true", help="Print CLASSES as JSON")
    args = p.parse_args()

    if args.list:
        print(json.dumps(CLASSES))
        return
    if args.class_name:
        asyncio.run(scrape_one(args.class_name))
        return
    asyncio.run(scrape_all())


if __name__ == "__main__":
    main()
