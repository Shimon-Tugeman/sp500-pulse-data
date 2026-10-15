"""Build a single self-contained dashboard page (data embedded) for publishing as a Claude artifact.

Usage: python scripts/build_page.py OUTPUT.html
"""
import datetime as dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
data = json.load(open(os.path.join(ROOT, "data", "latest.json")))
cutoff = (dt.date.today() - dt.timedelta(days=550)).isoformat()
for r in data["stocks"]:
    if r.get("period") and r["period"] < cutoff:
        r.update(rev=None, eps=None, pe=None, margin=None, period=None)
page = open(os.path.join(ROOT, "docs", "index.html")).read()
assert "/*DATA*/null" in page
page = page.replace("/*DATA*/null", json.dumps(data, separators=(",", ":")))
open(sys.argv[1], "w").write(page)
print(f"built {sys.argv[1]}: {len(data['stocks'])} stocks, as of {data['asOf']}")
