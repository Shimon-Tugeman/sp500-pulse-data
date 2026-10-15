# sp500-pulse-data

Nightly data for the **S&P 500 Pulse** dashboard.

Every weekday after the New York close, a GitHub Action (`.github/workflows/nightly.yml`) runs
`scripts/update_data.py`, which collects:

- index members and GICS sectors from Wikipedia
- daily closing prices and volume from Yahoo Finance
- revenue, earnings per share, net income and shares outstanding from SEC EDGAR filings

and saves them to `data/latest.json`. The dashboard in `docs/` reads that file.

To run it by hand: **Actions → Nightly market data → Run workflow**.
