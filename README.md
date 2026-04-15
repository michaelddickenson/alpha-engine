# Alpha Engine

**A self-hosted momentum-based stock portfolio management system.**

Alpha Engine automates the quantitative side of a momentum investing strategy: it scores S&P 500 stocks daily, generates biweekly rebalance trade plans, tracks your actual fills, and visualises performance — all through a clean web dashboard running on your own server.

---

## Features

- **Momentum Scoring** — Ranks the S&P 500 daily using a composite signal: 12-1 month momentum (60%), 6-month momentum (40%), and a volatility penalty (−30%). Quality-filters out stocks below $10.
- **Biweekly Rebalance Plans** — Every other Friday, generates a trade plan: what to buy, what to sell, how many dollars, priced off the latest close.
- **Trade Recording** — Log your actual broker fills (dollar-amount buys, share-count buys, sells) to keep the portfolio in sync. FIFO lot tracking for cost basis.
- **Performance Tracking** — Plots portfolio NAV vs SPY since inception, indexed to 100. Shows total return, unrealised P&L, and benchmark comparison.
- **Web Dashboard** — Secure, single-user dark-mode UI. No JavaScript framework — plain HTML/CSS served by Flask and Gunicorn.
- **Automated Daily Pipeline** — A cron job ingests prices, scores the universe, marks NAV, and emails the trade plan on rebalance days.
- **Admin Controls** — Force a rebalance, refresh prices/scores, update the S&P 500 universe, backfill price history, reset/seed the portfolio — all from the UI.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.10+, Flask, SQLAlchemy |
| Database | SQLite |
| Price Data | yfinance |
| Web Server | Gunicorn + nginx |
| Hosting | Any Linux VPS (e.g. Oracle Cloud Free Tier, DigitalOcean, Hetzner) |
| DNS / HTTPS | DuckDNS + Let's Encrypt (certbot) |
| Email | Gmail SMTP (app password) |
| Scheduling | cron |

---

## Architecture

```
                        ┌─────────────────────────────────────┐
                        │            Daily Cron (10am ET)      │
                        │                                      │
                        │  ingest_prices  →  score_universe   │
                        │       ↓                              │
                        │  mark_to_market  (on rebalance day:)│
                        │       ↓          → rebalance plan   │
                        │  (cron_runs log) → email to user    │
                        └──────────────────┬──────────────────┘
                                           │ writes to
                                    ┌──────▼──────┐
                                    │  SQLite DB  │
                                    │ portfolio.db│
                                    └──────┬──────┘
                                           │ reads from
                        ┌──────────────────▼──────────────────┐
                        │          Flask Web App               │
                        │                                      │
                        │  /          Dashboard + Holdings     │
                        │  /plan      Trade Plan (with tabs)   │
                        │  /record    Log Fills                │
                        │  /performance  NAV vs SPY Chart      │
                        │  /admin     Controls + Cron History  │
                        │  /settings  Contribution Schedule    │
                        └─────────────────────────────────────┘
                                    Gunicorn → nginx → HTTPS
```

---

## Setup

### Prerequisites

- Python 3.10+
- A Linux server (Ubuntu 22.04 recommended; any Linux VPS works)
- `nginx` and `certbot` for HTTPS (optional but recommended)
- A Gmail account with an [App Password](https://support.google.com/accounts/answer/185833) for email delivery

### 1. Clone & install

```bash
git clone https://github.com/michaelddickenson/alpha-engine.git
cd alpha-engine

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — set AE_WEB_USER, AE_WEB_PASS, and SMTP_* values
```

### 3. Initialise the database

```bash
python3 -c "
from src.db import get_engine, init_db
from src.config import DB_PATH
init_db(get_engine(DB_PATH), 'src/schema.sql')
print('Database initialised at', DB_PATH)
"
```

### 4. Seed the S&P 500 universe and backfill price history

```bash
# Download the current S&P 500 constituent list
python3 -m src.update_universe_sp500

# Backfill 8 years of daily prices (~10 min, one-time)
python3 -m src.ingest_prices --backfill

# Run the first momentum score
python3 -m src.score_universe
```

### 5. Seed your portfolio

Go to **Admin → Reset / Seed Portfolio** in the web UI and paste your holdings from your broker.

Format: `SYMBOL, SHARES, AVG_COST, YYYY-MM-DD` (one per line).

### 6. Start the web server

```bash
# Development
python3 web/app.py

# Production (Gunicorn)
.venv/bin/gunicorn -w 2 -b 127.0.0.1:8000 web.app:app
```

With nginx, proxy `localhost:8000` and add a Let's Encrypt cert:

```nginx
server {
    server_name yoursubdomain.duckdns.org;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 7. Set up the daily cron

```bash
crontab -e
```

Add:

```cron
# Daily at 10:00 AM ET (Mon–Fri) — ingest prices, score, mark NAV, email plan on rebalance days
0 10 * * 1-5 bash -lc 'source /path/to/.env && cd /path/to/alpha-engine && source .venv/bin/activate && python3 -m tools.run_cycle --send gmail >> logs/cron.log 2>&1'
```

### 8. Configure as a systemd service (optional)

```ini
# /etc/systemd/system/alpha-web.service
[Unit]
Description=Alpha Engine Web App
After=network.target

[Service]
User=youruser
WorkingDirectory=/path/to/alpha-engine
EnvironmentFile=/path/to/.env
ExecStart=/path/to/alpha-engine/.venv/bin/gunicorn -w 2 -b 127.0.0.1:8000 web.app:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now alpha-web
```

---

## Project Structure

```
alpha-engine/
├── src/
│   ├── config.py           # DB path, env config
│   ├── db.py               # SQLAlchemy engine + schema init
│   ├── schema.sql          # Database schema
│   ├── ingest_prices.py    # Daily price ingestion (yfinance)
│   ├── score_universe.py   # Momentum scoring engine
│   ├── mark_to_market.py   # Daily NAV recording
│   ├── rebalance.py        # Trade plan generation
│   ├── select_targets.py   # Position selection logic
│   ├── report.py           # Trade plan formatting
│   └── update_universe_sp500.py  # S&P 500 constituent sync
├── tools/
│   ├── run_cycle.py        # Daily cron orchestrator
│   ├── send_gmail.py       # Email delivery
│   └── check_state.py      # CLI portfolio status check
├── web/
│   └── app.py              # Flask web application
├── migrations/             # SQL migration scripts
├── data/                   # SQLite database (gitignored)
├── logs/                   # Cron and gunicorn logs (gitignored)
├── out/                    # Generated trade plan files (gitignored)
├── .env.example            # Environment variable template
└── requirements.txt
```
