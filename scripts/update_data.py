"""Nightly S&P 500 data build for the S&P 500 Pulse dashboard.

Sources (all free, no API key):
  * Index members and sectors: Wikipedia "List of S&P 500 companies"
  * Daily closes and volume:   Yahoo Finance via the yfinance package
  * Financial reports:         SEC EDGAR XBRL "companyfacts" API

Output: data/latest.json (and a copy in docs/ for the GitHub Pages site).
If one source fails, values from the previous run are kept so the page never goes blank.
"""
import datetime as dt
import io
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
import yfinance as yf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "latest.json")
PAGES_OUT = os.path.join(ROOT, "docs", "latest.json")
CHART_DAYS = 130  # about 6 months of trading days
SEC_UA = os.environ.get("SEC_CONTACT") or "SP500PulseData/1.0 (github.com/Shimon-Tugeman/sp500-pulse-data)"


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- members
def load_members():
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    html = requests.get(url, headers={"User-Agent": SEC_UA}, timeout=30).text
    t = pd.read_html(io.StringIO(html), attrs={"id": "constituents"})[0]
    t = t.rename(columns={"Symbol": "s", "Security": "n", "GICS Sector": "sec",
                          "GICS Sub-Industry": "ind", "CIK": "cik"})
    t["s"] = t["s"].str.strip()
    t["cik"] = t["cik"].astype(int)
    log(f"members: {len(t)}")
    return t[["s", "n", "sec", "ind", "cik"]].to_dict("records")


# ---------------------------------------------------------------- prices
def load_prices(symbols):
    ysym = {s: s.replace(".", "-") for s in symbols}
    start = (dt.date.today() - dt.timedelta(days=400)).isoformat()
    closes, vols = {}, {}
    chunks = [symbols[i:i + 100] for i in range(0, len(symbols), 100)]
    for ci, chunk in enumerate(chunks):
        for attempt in range(4):
            try:
                df = yf.download([ysym[s] for s in chunk], start=start, auto_adjust=True,
                                 group_by="ticker", progress=False, threads=True)
                for s in chunk:
                    y = ysym[s]
                    if y not in df.columns.get_level_values(0):
                        continue
                    sub = df[y][["Close", "Volume"]].dropna()
                    if len(sub) > 30:
                        closes[s] = sub["Close"]
                        vols[s] = sub["Volume"]
                break
            except Exception as e:  # rate limits etc.
                log(f"prices chunk {ci} attempt {attempt}: {e}")
                time.sleep(20 * (attempt + 1))
        time.sleep(2)
    log(f"prices: {len(closes)}/{len(symbols)}")
    return closes, vols


# ---------------------------------------------------------------- SEC reports
REV_TAGS = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
            "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
            "RevenuesNetOfInterestExpense", "SalesRevenueGoodsNet"]
NI_TAGS = ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"]
EPS_TAGS = ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic"]


def _d(s):
    return dt.date.fromisoformat(s)


def series(facts, tags, unit):
    """Best tag's entries split into discrete quarters and full years, keyed by period end."""
    best = None
    for tag in tags:
        node = facts.get("us-gaap", {}).get(tag, {}).get("units", {}).get(unit)
        if not node:
            continue
        q, y = {}, {}
        for e in node:
            if "start" not in e or e.get("form") not in ("10-Q", "10-K", "10-Q/A", "10-K/A", "20-F", "40-F"):
                continue
            days = (_d(e["end"]) - _d(e["start"])).days
            bucket = q if 80 <= days <= 100 else y if 340 <= days <= 380 else None
            if bucket is None:
                continue
            prev = bucket.get(e["end"])
            if prev is None or e.get("filed", "") > prev.get("filed", ""):
                bucket[e["end"]] = e
        latest = max(list(q) + list(y), default="")
        # prefer the tag with the most recent data
        if best is None or latest > best[2]:
            best = (q, y, latest)
    return (best[0], best[1]) if best else ({}, {})


def year_before(d, pool):
    target = _d(d) - dt.timedelta(days=364)
    for k in pool:
        if abs((_d(k) - target).days) <= 10:
            return pool[k]
    return None


def growth(q, y):
    """YoY growth of the latest reported period (quarter, or full year if that is newer)."""
    lq = max(q, default="")
    ly = max(y, default="")
    pool, last = (y, ly) if ly > lq else (q, lq)
    if not last:
        return None, None
    prev = year_before(last, pool)
    if not prev or prev["val"] == 0:
        return None, last
    g = (pool[last]["val"] - prev["val"]) / abs(prev["val"]) * 100
    return round(g, 1), last


def ttm(q, y):
    """Trailing twelve months = last full year + quarters since − same quarters a year before."""
    ly = max(y, default="")
    if not ly:
        return None
    total = y[ly]["val"]
    for k in q:
        if k > ly:
            prev = year_before(k, q)
            if prev is None:
                return None
            total += q[k]["val"] - prev["val"]
    return total


def shares_out(facts):
    node = facts.get("dei", {}).get("EntityCommonStockSharesOutstanding", {}).get("units", {}).get("shares", [])
    if not node:
        return None
    last = max(e["end"] for e in node)
    vals = {e["val"] for e in node if e["end"] == last}
    return float(sum(vals))


def fetch_facts(cik):
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    for attempt in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": SEC_UA, "Accept-Encoding": "gzip"}, timeout=60)
            if r.status_code == 200:
                return r.json().get("facts", {})
            if r.status_code == 404:
                return None
        except Exception:
            pass
        time.sleep(2 * (attempt + 1))
    return None


def fundamentals(cik):
    time.sleep(0.15)  # stay well under SEC's 10 requests/second
    f = fetch_facts(cik)
    if not f:
        return None
    rq, ry = series(f, REV_TAGS, "USD")
    nq, ny = series(f, NI_TAGS, "USD")
    eq, ey = series(f, EPS_TAGS, "USD/shares")
    rev_g, rev_end = growth(rq, ry)
    eps_g, eps_end = growth(eq, ey)
    rev_t, ni_t, eps_t = ttm(rq, ry), ttm(nq, ny), ttm(eq, ey)
    margin = round(ni_t / rev_t * 100, 1) if rev_t and ni_t is not None and rev_t > 0 else None
    return {"rev": rev_g, "eps": eps_g, "epsTTM": eps_t, "margin": margin,
            "shares": shares_out(f), "period": eps_end or rev_end}


# ---------------------------------------------------------------- build
def main():
    prev = {}
    if os.path.exists(OUT):
        try:
            prev = {d["s"]: d for d in json.load(open(OUT))["stocks"]}
        except Exception:
            pass

    members = load_members()
    symbols = [m["s"] for m in members]
    closes, vols = load_prices(symbols)

    ciks = sorted({m["cik"] for m in members})
    with ThreadPoolExecutor(max_workers=6) as ex:
        fund = dict(zip(ciks, ex.map(fundamentals, ciks)))
    log(f"SEC reports: {sum(1 for v in fund.values() if v)}/{len(ciks)}")
    cik_count = {}
    for m in members:
        cik_count[m["cik"]] = cik_count.get(m["cik"], 0) + 1

    year_start = dt.date(dt.date.today().year, 1, 1)
    stocks, dates = [], None
    for m in members:
        s, p = m["s"], prev.get(m["s"], {})
        if s not in closes:
            if p:
                stocks.append(p)
            continue
        c, v = closes[s], vols[s]
        before = c[c.index.date < year_start]
        f = fund.get(m["cik"]) or {}
        price = float(c.iloc[-1])
        shares = f.get("shares")
        cap = price * shares / cik_count[m["cik"]] / 1e9 if shares else p.get("cap")
        eps_ttm = f.get("epsTTM")
        pe = round(price / eps_ttm, 1) if eps_ttm and eps_ttm > 0 else None
        row = {
            "s": s, "n": m["n"], "sec": m["sec"], "ind": m["ind"],
            "cap": round(cap, 1) if cap else None,
            "px": [round(float(x), 2) for x in c.iloc[-CHART_DAYS:]],
            "vol": [round(float(x) / 1e6, 3) for x in v.iloc[-CHART_DAYS:]],
            "ytd0": round(float(before.iloc[-1]), 2) if len(before) else round(float(c.iloc[0]), 2),
            "rev": f.get("rev", p.get("rev")) if f else p.get("rev"),
            "eps": f.get("eps", p.get("eps")) if f else p.get("eps"),
            "pe": pe if f else p.get("pe"),
            "margin": f.get("margin", p.get("margin")) if f else p.get("margin"),
            "period": f.get("period", p.get("period")) if f else p.get("period"),
        }
        stocks.append(row)
        if dates is None or len(c) > len(dates):
            dates = [d.strftime("%Y-%m-%d") for d in c.index[-CHART_DAYS:]]

    if len(stocks) < 400:
        log("too few stocks, keeping previous file")
        sys.exit(1)
    out = {"asOf": dates[-1], "generated": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
           "dates": dates, "stocks": stocks}
    for path in (OUT, PAGES_OUT):
        with open(path, "w") as fh:
            json.dump(out, fh, separators=(",", ":"))
    log(f"wrote {len(stocks)} stocks, as of {out['asOf']}")


if __name__ == "__main__":
    main()
