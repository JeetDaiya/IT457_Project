"""Sent minus stored for every run folder, worked out from the raw files only (no database, nothing re-run).

    python loadtest/missing_check.py [results-dir]      writes <results-dir>/missing_check.csv

sent   = "started" in generator_summary.json (readings the generator tried to send)
stored = "stored rows" in db_summary.txt
lost_formula = the official per-device formula, as saved in db_summary.txt (cannot see losses at the end of a sequence)
The raw folders are only read.
"""

import csv
import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "results")
rows = []
for folder in sorted(p for p in root.iterdir() if p.is_dir() and (p / "db_summary.txt").exists()):
    db = (folder / "db_summary.txt").read_text()
    sent = json.loads((folder / "generator_summary.json").read_text())["started"]
    stored = int(re.search(r"stored rows: (\d+)", db).group(1))
    formula = int(re.search(r"distinct seq\): (-?\d+)", db).group(1))
    rows.append([folder.name, sent, stored, sent - stored, formula])

with open(root / "missing_check.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["run", "sent", "stored", "missing", "lost_formula"])
    w.writerows(rows)
print(f"{len(rows)} runs; runs with missing readings:")
for r in rows:
    if r[3] != 0 or r[4] != 0:
        print("  ", *r)
