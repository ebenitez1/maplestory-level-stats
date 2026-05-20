#!/usr/bin/env python3
"""Combine per-class partials (from matrix scrape jobs) into a single stats.json.

Reads data/partials/*.json (each emitted by `scrape.py --class <name>`) and
writes data/stats.json with the merged class buckets plus per-class status
metadata (so the UI can flag classes that hit the IP block).
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

THRESHOLDS = [270, 275, 280, 285, 290, 295, 300]
MIN_LEVEL = THRESHOLDS[0]


def main():
    root = Path(__file__).resolve().parent.parent
    partials_dir = root / "data" / "partials"
    out_path = root / "data" / "stats.json"

    if not partials_dir.exists():
        print(f"No partials directory at {partials_dir}", file=sys.stderr)
        sys.exit(1)

    classes = {}
    statuses = {}
    for p in sorted(partials_dir.glob("*.json")):
        try:
            d = json.loads(p.read_text())
        except Exception as e:
            print(f"Skipping {p.name}: {e}", file=sys.stderr)
            continue
        name = d.get("class")
        if not name:
            continue
        classes[name] = d.get("buckets", {str(t): 0 for t in THRESHOLDS})
        statuses[name] = {
            "status": d.get("status"),
            "seen": d.get("seen"),
            "total_count": d.get("total_count"),
            "stopped_at_page": d.get("stopped_at_page"),
        }

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "region": "GMS (North America)",
        "thresholds": THRESHOLDS,
        "min_level": MIN_LEVEL,
        "classes": {k: classes[k] for k in sorted(classes)},
        "statuses": {k: statuses[k] for k in sorted(statuses)},
    }
    out_path.write_text(json.dumps(out, indent=2))
    print(f"Wrote {out_path} with {len(classes)} classes", file=sys.stderr)


if __name__ == "__main__":
    main()
