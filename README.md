# Live Market Workstation

A local BTC-USD dashboard with one-minute Yahoo Finance candles, corresponding volume, and replay from SQLite.

## Start on Windows

From the project directory with Python 3.10 or newer:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn app:app
```

Open http://127.0.0.1:8000. FastAPI creates `data/market.sqlite3` and initializes its schema on startup. To use a different file, set the `MARKET_DB` environment variable before starting. The application uses public Yahoo Finance endpoints and requires no credentials. Vue and Lightweight Charts are served locally with their licenses.

## Use the dashboard

- **Live** indicates a recent Yahoo quote. **Stale** indicates a quote over 90 seconds old. **Unavailable** indicates a connection failure or a simulated outage. The data age is measured from the provider timestamp.
- The **SQLite observation** number identifies the latest displayed quote's committed row. **Simulate outage** pauses Yahoo ingestion and keeps the existing chart visible. **Resume feed** reconnects to Yahoo.
- **Replay** plays up to 120 saved observations in receipt order at 10 observations per second. **Back to feed** restores the current dashboard. Replay works with an existing database even when Yahoo is unreachable.

Run the deterministic checks with `.venv\Scripts\python.exe -m unittest discover -s tests -v`. See the [design notes](docs/design.md).
