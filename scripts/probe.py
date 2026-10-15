"""Quick check of which data sources answer from the GitHub runner."""
import requests, traceback

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
SEC = {"User-Agent": "SP500PulseData/1.0 (github.com/Shimon-Tugeman/sp500-pulse-data)"}
tests = {
    "yahoo_chart_q1": ("https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=1mo&interval=1d", UA),
    "yahoo_chart_q2": ("https://query2.finance.yahoo.com/v8/finance/chart/AAPL?range=1mo&interval=1d", UA),
    "stooq": ("https://stooq.com/q/d/l/?s=aapl.us&i=d", UA),
    "nasdaq": ("https://api.nasdaq.com/api/quote/AAPL/historical?assetclass=stocks&fromdate=2026-09-01&limit=50", UA),
    "sec_facts": ("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json", SEC),
    "wikipedia": ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", SEC),
}
for name, (url, h) in tests.items():
    try:
        r = requests.get(url, headers=h, timeout=20)
        print(f"::notice::{name} {r.status_code} {len(r.content)}B {r.text[:120]!r}")
    except Exception as e:
        print(f"::notice::{name} EXC {e!r}"[:300])
try:
    import yfinance as yf
    df = yf.download(["AAPL", "MSFT"], period="1mo", progress=False, auto_adjust=True, group_by="ticker")
    print(f"::notice::yfinance rows={len(df)} cols={list(df.columns)[:3]}")
except Exception as e:
    print(f"::notice::yfinance EXC {traceback.format_exc()[-250:]!r}")
