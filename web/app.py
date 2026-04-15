"""
Alpha Engine Web Application
Self-hosted momentum portfolio management dashboard.
"""
from __future__ import annotations

import os
import subprocess
import json
import traceback
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from typing import Optional

import pytz
from flask import Flask, request, Response, redirect, url_for
from sqlalchemy import text

from src.db import get_engine, init_db
from src.config import DB_PATH, VENV_PYTHON

app = Flask(__name__)
ET = pytz.timezone("America/New_York")

APP_USER = os.getenv("AE_WEB_USER", os.getenv("WEB_USER", "alpha"))
APP_PASS = os.getenv("AE_WEB_PASS", os.getenv("WEB_PASS", "change-me"))
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "src" / "schema.sql"
OUT_DIR = PROJECT_ROOT / "out"


# ─────────────────────────────────────────────
#  Auth
# ─────────────────────────────────────────────

def _unauth():
    return Response("Unauthorized", 401, {"WWW-Authenticate": 'Basic realm="alpha_engine"'})

def _check_auth() -> bool:
    auth = request.authorization
    return bool(auth and auth.username == APP_USER and auth.password == APP_PASS)


# ─────────────────────────────────────────────
#  DB helpers
# ─────────────────────────────────────────────

def engine():
    e = get_engine(DB_PATH)
    try:
        init_db(e, str(SCHEMA_PATH))
    except Exception:
        pass
    return e


def get_cash(conn) -> float:
    row = conn.execute(text("SELECT value FROM state WHERE key='cash'")).fetchone()
    return float(row[0]) if row else 0.0


def set_cash(conn, cash: float):
    conn.execute(text("""
        INSERT INTO state(key, value) VALUES ('cash', :v)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """), {"v": str(float(cash))})


def get_meta(conn, key: str) -> Optional[str]:
    row = conn.execute(text("SELECT value FROM portfolio_meta WHERE key=:k"), {"k": key}).fetchone()
    return row[0] if row else None


def set_meta(conn, key: str, value: str):
    conn.execute(text("""
        INSERT INTO portfolio_meta(key, value) VALUES (:k, :v)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """), {"k": key, "v": value})


def log_action(conn, action: str, details: str = "", success: bool = True, error: str = ""):
    try:
        conn.execute(text("""
            INSERT INTO admin_log(timestamp_utc, action, user, details, success, error_message)
            VALUES (:ts, :act, :usr, :det, :suc, :err)
        """), {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "act": action, "usr": APP_USER, "det": details,
            "suc": 1 if success else 0, "err": error,
        })
    except Exception:
        pass


def run_script(*module_args, timeout: int = 600) -> tuple[bool, str, str]:
    """Run a Python module using the venv Python. Returns (success, stdout, stderr)."""
    python = VENV_PYTHON if Path(VENV_PYTHON).exists() else "python3"
    cmd = [python, "-m"] + list(module_args)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, cwd=str(PROJECT_ROOT)
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", f"Timed out after {timeout}s"
    except Exception as e:
        return False, "", str(e)


# ─────────────────────────────────────────────
#  CSS / Design System
# ─────────────────────────────────────────────

CSS = """
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@300;400;500&family=DM+Sans:wght@300;400;500;600&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:       #0a0e17;
  --surface:  #111827;
  --surface2: #1a2235;
  --border:   #1f2d45;
  --accent:   #3b82f6;
  --accent2:  #60a5fa;
  --green:    #10b981;
  --red:      #ef4444;
  --amber:    #f59e0b;
  --text:     #e2e8f0;
  --muted:    #64748b;
  --mono:     'DM Mono', monospace;
  --sans:     'DM Sans', sans-serif;
  --radius:   8px;
  --radius-lg:14px;
  --sidebar-w: 220px;
  --sidebar-collapsed-w: 60px;
}

body {
  font-family: var(--sans);
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  font-size: 14px;
  line-height: 1.6;
}

/* ── Layout ───────────────────────────────── */
.shell { display: flex; min-height: 100vh; }

.sidebar {
  width: var(--sidebar-w);
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  padding: 0 0 24px;
  position: fixed;
  height: 100vh;
  overflow-y: auto;
  overflow-x: hidden;
  z-index: 100;
  transition: width 0.25s ease;
}

/* ── Sidebar header (logo + toggle) ──────── */
.sidebar-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 20px 20px 20px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 8px;
  gap: 8px;
  min-height: 72px;
}

.sidebar-logo-text .wordmark {
  font-family: var(--mono);
  font-size: 12px;
  font-weight: 500;
  color: var(--accent2);
  letter-spacing: 0.15em;
  text-transform: uppercase;
  white-space: nowrap;
}

.sidebar-logo-text .tagline {
  font-size: 11px;
  color: var(--muted);
  margin-top: 2px;
  white-space: nowrap;
}

/* Desktop sidebar toggle (inside sidebar) */
.toggle-btn {
  background: transparent;
  border: none;
  color: var(--muted);
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  padding: 4px 6px;
  border-radius: var(--radius);
  flex-shrink: 0;
  transition: color 0.15s, background 0.15s;
  align-self: flex-start;
  margin-top: 1px;
}
.toggle-btn:hover { color: var(--text); background: var(--surface2); }

/* ── Nav items ────────────────────────────── */
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 20px;
  color: var(--muted);
  text-decoration: none;
  font-size: 13px;
  font-weight: 500;
  border-left: 2px solid transparent;
  transition: all 0.15s;
  white-space: nowrap;
  overflow: hidden;
}

.nav-item:hover { color: var(--text); background: var(--surface2); }
.nav-item.active { color: var(--accent2); border-left-color: var(--accent); background: rgba(59,130,246,0.08); }

.nav-abbr {
  display: none;
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  min-width: 24px;
  text-align: center;
}

.nav-section {
  padding: 16px 20px 6px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.1em;
  color: var(--muted);
  text-transform: uppercase;
  white-space: nowrap;
  overflow: hidden;
}

/* ── Main content ─────────────────────────── */
.main {
  margin-left: var(--sidebar-w);
  padding: 32px;
  max-width: 1200px;
  width: 100%;
  transition: margin-left 0.25s ease;
}

/* ── Collapsed sidebar (desktop) ─────────── */
.sidebar.collapsed {
  width: var(--sidebar-collapsed-w);
}

.sidebar.collapsed .sidebar-header {
  justify-content: center;
  padding: 18px 0 18px;
}

.sidebar.collapsed .sidebar-logo-text { display: none; }
.sidebar.collapsed .nav-section { opacity: 0; pointer-events: none; }
.sidebar.collapsed .nav-item {
  justify-content: center;
  padding: 10px 0;
  border-left-width: 0;
  border-right: 2px solid transparent;
}
.sidebar.collapsed .nav-item.active {
  border-right-color: var(--accent);
  background: rgba(59,130,246,0.08);
}
.sidebar.collapsed .nav-label { display: none; }
.sidebar.collapsed .nav-abbr { display: block; }

body.sidebar-collapsed .main { margin-left: var(--sidebar-collapsed-w); }

/* ── Sidebar backdrop (mobile overlay) ────── */
.sidebar-backdrop {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.6);
  z-index: 99;
  cursor: pointer;
}
.sidebar-backdrop.visible { display: block; }

/* Mobile-only floating toggle */
.toggle-btn-mobile {
  display: none;
  position: fixed;
  top: 12px;
  left: 12px;
  z-index: 101;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text);
  font-size: 18px;
  cursor: pointer;
  padding: 6px 10px;
  line-height: 1;
  align-items: center;
  justify-content: center;
  transition: background 0.15s;
}
.toggle-btn-mobile:hover { background: var(--surface2); }

/* ── Page header ──────────────────────────── */
.page-header { margin-bottom: 28px; }
.page-title { font-size: 22px; font-weight: 600; color: var(--text); }
.page-sub { font-size: 13px; color: var(--muted); margin-top: 4px; }

/* ── Cards ────────────────────────────────── */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px;
  margin-bottom: 20px;
}

.card-title {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 16px;
}

/* ── Stat tiles ───────────────────────────── */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}

.stat-tile {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px;
}

.stat-label { font-size: 11px; color: var(--muted); font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; }
.stat-value { font-family: var(--mono); font-size: 24px; font-weight: 500; margin-top: 6px; color: var(--text); }
.stat-sub { font-size: 12px; color: var(--muted); margin-top: 4px; }
.stat-up { color: var(--green); }
.stat-down { color: var(--red); }

/* ── Tables ───────────────────────────────── */
.tbl-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }

.tbl { width: 100%; border-collapse: collapse; }
.tbl th {
  text-align: left;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted);
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
}
.tbl th.r { text-align: right; }
.tbl td { padding: 10px 12px; border-bottom: 1px solid rgba(31,45,69,0.5); font-size: 13px; }
.tbl td.r { text-align: right; font-family: var(--mono); font-size: 12px; }
.tbl tr:last-child td { border-bottom: none; }
.tbl tr:hover td { background: var(--surface2); }
.tbl tfoot tr td { border-top: 2px solid var(--border); padding: 10px 12px; }
.sym { font-family: var(--mono); font-weight: 500; font-size: 13px; color: var(--accent2); }
.pos { color: var(--green); }
.neg { color: var(--red); }

/* ── Buttons ──────────────────────────────── */
.btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 16px;
  border: none; border-radius: var(--radius);
  font-family: var(--sans); font-size: 13px; font-weight: 500;
  cursor: pointer; transition: all 0.15s;
  text-decoration: none;
  white-space: nowrap;
}
.btn-primary { background: var(--accent); color: #fff; }
.btn-primary:hover { background: var(--accent2); }
.btn-ghost { background: transparent; color: var(--muted); border: 1px solid var(--border); }
.btn-ghost:hover { color: var(--text); border-color: var(--muted); }
.btn-danger { background: rgba(239,68,68,0.15); color: var(--red); border: 1px solid rgba(239,68,68,0.3); }
.btn-danger:hover { background: rgba(239,68,68,0.25); }
.btn-success { background: rgba(16,185,129,0.15); color: var(--green); border: 1px solid rgba(16,185,129,0.3); }
.btn-sm { padding: 5px 10px; font-size: 12px; }
.btn-lg { padding: 12px 24px; font-size: 15px; }
.btn-block { width: 100%; justify-content: center; }

/* ── Forms ────────────────────────────────── */
.form-group { margin-bottom: 16px; }
.form-label { display: block; font-size: 12px; font-weight: 600; color: var(--muted); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.06em; }
.form-input {
  width: 100%; padding: 9px 12px;
  background: var(--bg); border: 1px solid var(--border);
  border-radius: var(--radius); color: var(--text);
  font-family: var(--sans); font-size: 13px;
  transition: border-color 0.15s;
}
.form-input:focus { outline: none; border-color: var(--accent); }
.form-input::placeholder { color: var(--muted); }
textarea.form-input { resize: vertical; font-family: var(--mono); font-size: 12px; }
.form-hint { font-size: 11px; color: var(--muted); margin-top: 4px; }

/* ── Alerts ───────────────────────────────── */
.alert { padding: 12px 16px; border-radius: var(--radius); margin-bottom: 16px; font-size: 13px; }
.alert-error { background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.3); color: #fca5a5; }
.alert-success { background: rgba(16,185,129,0.1); border: 1px solid rgba(16,185,129,0.3); color: #6ee7b7; }
.alert-info { background: rgba(59,130,246,0.1); border: 1px solid rgba(59,130,246,0.3); color: #93c5fd; }
.alert-warning { background: rgba(245,158,11,0.1); border: 1px solid rgba(245,158,11,0.3); color: #fcd34d; }

/* ── Badge ────────────────────────────────── */
.badge { display: inline-block; padding: 2px 8px; border-radius: 9999px; font-size: 11px; font-weight: 600; }
.badge-green { background: rgba(16,185,129,0.15); color: var(--green); }
.badge-red { background: rgba(239,68,68,0.15); color: var(--red); }
.badge-amber { background: rgba(245,158,11,0.15); color: var(--amber); }
.badge-blue { background: rgba(59,130,246,0.15); color: var(--accent2); }

/* ── Two-col grid ─────────────────────────── */
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }

/* ── Pre / code ───────────────────────────── */
pre {
  background: var(--bg); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 16px;
  font-family: var(--mono); font-size: 12px;
  overflow-x: auto; white-space: pre-wrap;
  color: var(--text); max-height: 400px; overflow-y: auto;
}

/* ── Progress bar ─────────────────────────── */
.progress-bar { background: var(--border); border-radius: 4px; height: 4px; overflow: hidden; margin-top: 8px; }
.progress-fill { height: 100%; border-radius: 4px; background: var(--accent); transition: width 0.3s; }

/* ── Divider ──────────────────────────────── */
hr { border: none; border-top: 1px solid var(--border); margin: 20px 0; }

/* ── Log entries ──────────────────────────── */
.log-entry { padding: 8px 12px; border-left: 3px solid var(--border); margin-bottom: 6px; font-size: 12px; font-family: var(--mono); }
.log-entry.ok { border-color: var(--green); }
.log-entry.fail { border-color: var(--red); }
.log-entry.warn { border-color: var(--amber); }

/* ── Scrollbar ────────────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

/* ── Utilities ────────────────────────────── */
.mt-4 { margin-top: 16px; }
.mt-8 { margin-top: 32px; }
.mb-4 { margin-bottom: 16px; }
.flex { display: flex; }
.flex-wrap { flex-wrap: wrap; }
.items-center { align-items: center; }
.gap-2 { gap: 8px; }
.gap-4 { gap: 16px; }
.justify-between { justify-content: space-between; }
.text-muted { color: var(--muted); }
.text-mono { font-family: var(--mono); }
.text-sm { font-size: 12px; }
.font-medium { font-weight: 500; }

/* ── Tablet breakpoint ────────────────────── */
@media (max-width: 900px) {
  .grid-2 { grid-template-columns: 1fr; }
}

/* ── Mobile breakpoint ────────────────────── */
@media (max-width: 768px) {
  .sidebar {
    position: fixed;
    height: 100vh;
    z-index: 100;
    width: 220px !important;
    transform: translateX(-100%);
    transition: transform 0.25s ease;
  }
  .sidebar.mobile-open {
    transform: translateX(0);
  }
  /* Always show full labels on mobile, even if desktop is collapsed */
  .sidebar.mobile-open .sidebar-logo-text { display: block; }
  .sidebar.mobile-open .sidebar-header { justify-content: space-between; padding: 20px; }
  .sidebar.mobile-open .nav-section { opacity: 1; pointer-events: auto; }
  .sidebar.mobile-open .nav-item { justify-content: flex-start; padding: 10px 20px; border-left-width: 2px; border-right-width: 0; }
  .sidebar.mobile-open .nav-item.active { border-left-color: var(--accent); border-right-color: transparent; }
  .sidebar.mobile-open .nav-label { display: inline; }
  .sidebar.mobile-open .nav-abbr { display: none; }

  .main {
    margin-left: 0 !important;
    padding: 56px 16px 24px;
    max-width: 100%;
  }

  .toggle-btn-mobile { display: flex; }

  /* Stack stat tiles 2-up on small screens */
  .stat-grid { grid-template-columns: 1fr 1fr; }

  /* Full-width table scroll */
  .tbl-scroll { margin: 0 -20px; padding: 0 20px; }

  /* Wrap flex button groups */
  .btn-row { flex-wrap: wrap; }
}

@media (max-width: 480px) {
  .stat-grid { grid-template-columns: 1fr; }
  .main { padding: 52px 12px 20px; }
  .page-title { font-size: 18px; }
  .stat-value { font-size: 20px; }
}
"""

# ── Sidebar JS ────────────────────────────────────────────────────────────
SIDEBAR_JS = """
<script>
(function() {
  var sidebar  = document.getElementById('ae-sidebar');
  var backdrop = document.getElementById('ae-backdrop');
  var dtToggle = document.getElementById('ae-toggle-dt');
  var mbToggle = document.getElementById('ae-toggle-mb');

  function isDesktop() { return window.innerWidth >= 768; }

  function applyDesktopState() {
    if (!isDesktop()) { return; }
    if (localStorage.getItem('ae_sidebar') === 'collapsed') {
      sidebar.classList.add('collapsed');
      document.body.classList.add('sidebar-collapsed');
    } else {
      sidebar.classList.remove('collapsed');
      document.body.classList.remove('sidebar-collapsed');
    }
  }

  function closeMobile() {
    sidebar.classList.remove('mobile-open');
    backdrop.classList.remove('visible');
    document.body.style.overflow = '';
  }

  function openMobile() {
    sidebar.classList.add('mobile-open');
    backdrop.classList.add('visible');
    document.body.style.overflow = 'hidden';
  }

  dtToggle.addEventListener('click', function() {
    if (!isDesktop()) {
      sidebar.classList.toggle('mobile-open') ? (backdrop.classList.add('visible'), document.body.style.overflow = 'hidden')
                                              : (backdrop.classList.remove('visible'), document.body.style.overflow = '');
      return;
    }
    var collapsed = sidebar.classList.toggle('collapsed');
    document.body.classList.toggle('sidebar-collapsed', collapsed);
    localStorage.setItem('ae_sidebar', collapsed ? 'collapsed' : 'expanded');
  });

  mbToggle.addEventListener('click', function() {
    sidebar.classList.contains('mobile-open') ? closeMobile() : openMobile();
  });

  backdrop.addEventListener('click', closeMobile);

  window.addEventListener('resize', function() {
    if (isDesktop()) { closeMobile(); applyDesktopState(); }
  });

  applyDesktopState();
})();
</script>
"""


def page(title: str, content: str, active: str = "") -> str:
    nav_items = [
        ("home",        "/",           "DB", "Dashboard"),
        ("portfolio",   "/portfolio",  "PF", "Portfolio"),
        ("plan",        "/plan",       "TP", "Trade Plan"),
        ("record",      "/record",     "RT", "Record Trades"),
        ("performance", "/performance","PE", "Performance"),
        ("admin",       "/admin",      "AD", "Admin"),
        ("settings",    "/settings",   "ST", "Settings"),
    ]

    nav_html = '<div class="nav-section">Navigation</div>'
    for key, href, abbr, label in nav_items:
        cls = "nav-item active" if key == active else "nav-item"
        nav_html += (
            f'<a href="{href}" class="{cls}">'
            f'<span class="nav-abbr">{abbr}</span>'
            f'<span class="nav-label">{label}</span>'
            f'</a>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Alpha Engine</title>
<style>{CSS}</style>
</head>
<body>
<div class="shell">
  <button class="toggle-btn-mobile" id="ae-toggle-mb" aria-label="Open navigation">&#9776;</button>
  <div class="sidebar-backdrop" id="ae-backdrop"></div>

  <aside class="sidebar" id="ae-sidebar">
    <div class="sidebar-header">
      <div class="sidebar-logo-text">
        <div class="wordmark">ALPHA ENGINE</div>
        <div class="tagline">Momentum Portfolio</div>
      </div>
      <button class="toggle-btn" id="ae-toggle-dt" aria-label="Toggle sidebar">&#9776;</button>
    </div>
    {nav_html}
  </aside>

  <main class="main" id="ae-main">
    {content}
  </main>
</div>
{SIDEBAR_JS}
</body>
</html>"""


# ─────────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────────

def _dashboard_content() -> str:
    """Dashboard: summary stats + quick holdings overview."""
    e = engine()
    with e.begin() as conn:
        cash = get_cash(conn)
        holdings = conn.execute(text("""
            SELECT h.symbol, h.shares, h.avg_cost, p.adj_close
            FROM holdings h
            LEFT JOIN (
                SELECT pd.symbol, pd.adj_close
                FROM prices_daily pd
                INNER JOIN (SELECT symbol, MAX(date) as md FROM prices_daily GROUP BY symbol) l
                ON pd.symbol=l.symbol AND pd.date=l.md
            ) p ON h.symbol=p.symbol
            WHERE h.shares > 0.0001 ORDER BY h.symbol
        """)).fetchall()

        next_reb = get_meta(conn, "next_rebalance_date") or "—"
        default_contrib = get_meta(conn, "default_contribution") or "0"

        cron = conn.execute(text("""
            SELECT run_date, status, steps_completed, error_message
            FROM cron_runs ORDER BY id DESC LIMIT 1
        """)).fetchone()

    total_value = cash
    total_cost = cash
    for sym, sh, ac, px in holdings:
        if px:
            total_value += float(sh) * float(px)
            total_cost += float(sh) * float(ac)

    total_gl = total_value - total_cost
    gl_pct = (total_gl / total_cost * 100) if total_cost > 0 else 0
    gl_class = "stat-up" if total_gl >= 0 else "stat-down"
    gl_sign = "+" if total_gl >= 0 else ""

    cron_badge = ""
    if cron:
        s = cron[1]
        if s == "ok":
            cron_badge = f'<span class="badge badge-green">Last run: {cron[0]} ✓</span>'
        elif "partial" in s:
            cron_badge = f'<span class="badge badge-amber">Last run: {cron[0]} ⚠ partial</span>'
        else:
            cron_badge = f'<span class="badge badge-red">Last run: {cron[0]} ✗ error</span>'

    rows = ""
    for sym, sh, ac, px in holdings:
        sh, ac = float(sh), float(ac)
        px_val = float(px) if px else 0.0
        mv = sh * px_val
        cb = sh * ac
        gl = mv - cb
        gl_p = (gl / cb * 100) if cb > 0 else 0
        gc = "pos" if gl >= 0 else "neg"
        sign = "+" if gl >= 0 else ""
        rows += (
            f'<tr>'
            f'<td><span class="sym">{sym}</span></td>'
            f'<td class="r">{sh:.4f}</td>'
            f'<td class="r">${ac:.2f}</td>'
            f'<td class="r">${px_val:.2f}</td>'
            f'<td class="r">${mv:.2f}</td>'
            f'<td class="r {gc}">{sign}${gl:.2f} ({sign}{gl_p:.1f}%)</td>'
            f'</tr>'
        )

    return f"""
<div class="page-header flex items-center justify-between">
  <div>
    <div class="page-title">Dashboard</div>
    <div class="page-sub">Portfolio overview</div>
  </div>
  {cron_badge}
</div>

<div class="stat-grid">
  <div class="stat-tile">
    <div class="stat-label">Total Value</div>
    <div class="stat-value">${total_value:,.2f}</div>
    <div class="stat-sub text-muted">{len(holdings)} positions + cash</div>
  </div>
  <div class="stat-tile">
    <div class="stat-label">Cash</div>
    <div class="stat-value">${cash:,.2f}</div>
    <div class="stat-sub text-muted">{cash/total_value*100:.1f}% of portfolio</div>
  </div>
  <div class="stat-tile">
    <div class="stat-label">Total Gain / Loss</div>
    <div class="stat-value {gl_class}">{gl_sign}${total_gl:,.2f}</div>
    <div class="stat-sub {gl_class}">{gl_sign}{gl_pct:.2f}%</div>
  </div>
  <div class="stat-tile">
    <div class="stat-label">Next Rebalance</div>
    <div class="stat-value" style="font-size:18px">{next_reb}</div>
    <div class="stat-sub text-muted">Contribution: ${float(default_contrib or 0):,.0f}</div>
  </div>
</div>

<div class="card">
  <div class="card-title">Holdings Summary</div>
  <div class="tbl-scroll">
  <table class="tbl">
    <thead><tr>
      <th>Symbol</th><th class="r">Shares</th><th class="r">Avg Cost</th>
      <th class="r">Price</th><th class="r">Value</th><th class="r">Gain/Loss</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
  </div>
</div>

<div class="flex gap-4 mt-4 btn-row">
  <a href="/record" class="btn btn-primary">Record Trades</a>
  <a href="/plan" class="btn btn-ghost">View Trade Plan</a>
  <a href="/performance" class="btn btn-ghost">Performance</a>
</div>
"""


def _portfolio_content() -> str:
    """Portfolio: full cost-basis detail + recent fills. Distinct from Dashboard."""
    e = engine()
    with e.begin() as conn:
        cash = get_cash(conn)
        holdings = conn.execute(text("""
            SELECT h.symbol, h.shares, h.avg_cost, p.adj_close, p.date
            FROM holdings h
            LEFT JOIN (
                SELECT pd.symbol, pd.adj_close, pd.date
                FROM prices_daily pd
                INNER JOIN (SELECT symbol, MAX(date) as md FROM prices_daily GROUP BY symbol) l
                ON pd.symbol=l.symbol AND pd.date=l.md
            ) p ON h.symbol=p.symbol
            WHERE h.shares > 0.0001
            ORDER BY h.shares * COALESCE(p.adj_close, h.avg_cost) DESC
        """)).fetchall()

        fills = conn.execute(text("""
            SELECT fill_time_utc, symbol, side, shares, price, fees
            FROM fills ORDER BY id DESC LIMIT 15
        """)).fetchall()

        # Lot detail per symbol
        lots = conn.execute(text("""
            SELECT symbol, COUNT(*) as lot_count,
                   SUM(shares_remaining) as open_shares,
                   MIN(buy_time_utc) as first_buy
            FROM lots
            WHERE shares_remaining > 0.0001
            GROUP BY symbol
        """)).fetchall()
        lot_map = {r[0]: r for r in lots}

    total_book = cash
    total_mkt = cash

    rows = ""
    for sym, sh, ac, px, px_date in holdings:
        sh, ac = float(sh), float(ac)
        px_val = float(px) if px else 0.0
        book = sh * ac
        mkt = sh * px_val
        pnl = mkt - book
        pnl_pct = (pnl / book * 100) if book > 0 else 0
        total_book += book
        total_mkt += mkt
        gc = "pos" if pnl >= 0 else "neg"
        sign = "+" if pnl >= 0 else ""
        lot_info = lot_map.get(sym)
        lot_count = lot_info[1] if lot_info else 1
        price_age = f'<span class="text-muted text-sm">{px_date}</span>' if px_date else '<span class="text-muted">—</span>'
        rows += (
            f'<tr>'
            f'<td><span class="sym">{sym}</span>'
            f'<span style="font-size:10px;color:var(--muted);margin-left:6px">{lot_count} lot{"s" if lot_count != 1 else ""}</span></td>'
            f'<td class="r">{sh:.4f}</td>'
            f'<td class="r">${ac:.2f}</td>'
            f'<td class="r">${book:.2f}</td>'
            f'<td class="r">${px_val:.2f}<br>{price_age}</td>'
            f'<td class="r">${mkt:.2f}</td>'
            f'<td class="r {gc}">{sign}${pnl:.2f}</td>'
            f'<td class="r {gc}">{sign}{pnl_pct:.1f}%</td>'
            f'</tr>'
        )

    total_pnl = total_mkt - total_book
    total_pct = (total_pnl / total_book * 100) if total_book > 0 else 0
    tc = "pos" if total_pnl >= 0 else "neg"
    ts = "+" if total_pnl >= 0 else ""

    fills_rows = ""
    for ts_fill, sym, side, sh, px, fees in fills:
        side_cls = "pos" if side == "BUY" else "neg"
        val = float(sh) * float(px)
        fills_rows += (
            f'<tr>'
            f'<td class="text-muted text-sm">{ts_fill[:10]}</td>'
            f'<td><span class="sym">{sym}</span></td>'
            f'<td class="{side_cls}">{side}</td>'
            f'<td class="r">{float(sh):.4f}</td>'
            f'<td class="r">${float(px):.2f}</td>'
            f'<td class="r">${val:.2f}</td>'
            f'</tr>'
        )

    fills_section = (
        '<table class="tbl"><thead><tr>'
        '<th>Date</th><th>Symbol</th><th>Side</th>'
        '<th class="r">Shares</th><th class="r">Price</th><th class="r">Value</th>'
        '</tr></thead><tbody>' + fills_rows + '</tbody></table>'
    ) if fills_rows else '<p class="text-muted text-sm">No fills recorded yet.</p>'

    return f"""
<div class="page-header flex items-center justify-between">
  <div>
    <div class="page-title">Portfolio</div>
    <div class="page-sub">Holdings detail — cost basis, lot count, and unrealised P&amp;L</div>
  </div>
  <a href="/record" class="btn btn-primary btn-sm">Record Trades</a>
</div>

<div class="card">
  <div class="card-title">Positions</div>
  <div class="tbl-scroll">
  <table class="tbl">
    <thead><tr>
      <th>Symbol</th>
      <th class="r">Shares</th>
      <th class="r">Avg Cost</th>
      <th class="r">Book Cost</th>
      <th class="r">Latest Price</th>
      <th class="r">Mkt Value</th>
      <th class="r">Unrealised P&amp;L</th>
      <th class="r">P&amp;L %</th>
    </tr></thead>
    <tbody>{rows}</tbody>
    <tfoot>
      <tr>
        <td colspan="3" style="color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.06em">
          Total (incl. cash ${cash:,.2f})
        </td>
        <td class="r">${total_book:,.2f}</td>
        <td></td>
        <td class="r">${total_mkt:,.2f}</td>
        <td class="r {tc}">{ts}${total_pnl:,.2f}</td>
        <td class="r {tc}">{ts}{total_pct:.1f}%</td>
      </tr>
    </tfoot>
  </table>
  </div>
</div>

<div class="card">
  <div class="card-title">Recent Activity</div>
  <div class="tbl-scroll">{fills_section}</div>
</div>
"""


@app.get("/")
def index():
    if not _check_auth(): return _unauth()
    return Response(page("Dashboard", _dashboard_content(), "home"), mimetype="text/html")


@app.get("/portfolio")
def portfolio():
    if not _check_auth(): return _unauth()
    return Response(page("Portfolio", _portfolio_content(), "portfolio"), mimetype="text/html")


@app.get("/status")
def status():
    if not _check_auth(): return _unauth()
    return redirect("/portfolio")


@app.get("/plan")
def plan():
    if not _check_auth(): return _unauth()

    OUT_DIR.mkdir(exist_ok=True)
    plans = sorted(OUT_DIR.glob("trade_plan_*.txt"), reverse=True)

    plan_list = ""
    plan_content = "No trade plans found yet."
    sel_date = request.args.get("date")

    if plans:
        latest = plans[0]
        plan_content = latest.read_text(encoding="utf-8", errors="replace")

        active_date = sel_date if sel_date else latest.stem.replace("trade_plan_", "")
        plan_list = '<div class="flex gap-2 mb-4 flex-wrap">'
        for p in plans[:10]:
            date_str = p.stem.replace("trade_plan_", "")
            tab_cls = "btn-primary" if date_str == active_date else "btn-ghost"
            plan_list += f'<a href="/plan?date={date_str}" class="btn btn-sm {tab_cls}">{date_str}</a>'
        plan_list += '</div>'

    if sel_date:
        sel_path = OUT_DIR / f"trade_plan_{sel_date}.txt"
        if sel_path.exists():
            plan_content = sel_path.read_text(encoding="utf-8", errors="replace")

    content = f"""
<div class="page-header">
  <div class="page-title">Trade Plan</div>
  <div class="page-sub">Biweekly rebalance recommendations — execute manually in your broker</div>
</div>

{plan_list}

<div class="card">
  <div class="flex justify-between items-center mb-4">
    <div class="card-title" style="margin-bottom:0">Latest Plan</div>
    <form method="POST" action="/admin/force-rebalance" style="display:inline">
      <button type="submit" class="btn btn-ghost btn-sm">Generate New Plan</button>
    </form>
  </div>
  <pre>{plan_content}</pre>
</div>

<div class="alert alert-info">
  After executing trades in your broker, go to <a href="/record" style="color:var(--accent2)">Record Trades</a> to log your actual fills.
</div>
"""
    return Response(page("Trade Plan", content, "plan"), mimetype="text/html")


@app.get("/record")
def record():
    if not _check_auth(): return _unauth()

    e = engine()
    with e.begin() as conn:
        cash = get_cash(conn)

    content = f"""
<div class="page-header">
  <div class="page-title">Record Trades</div>
  <div class="page-sub">Log your actual broker fills to keep the portfolio in sync</div>
</div>

<div class="grid-2">
  <div class="card">
    <div class="card-title">Log Executed Trades</div>
    <p class="text-muted text-sm mb-4">Enter one trade per line. Format:<br>
    <span class="text-mono" style="color:var(--accent2)">ACTION, SYMBOL, AMOUNT, PRICE[, FEES]</span></p>

    <div class="card" style="margin-bottom:16px;padding:12px;background:var(--bg)">
      <div class="text-sm text-muted" style="margin-bottom:6px">Examples:</div>
      <pre style="border:none;padding:0;background:none;max-height:none">BUYD, JNJ, 100.00, 240.86
BUY, GOOGL, 0.117, 337.12
SELL, DG, 0.069, 121.56</pre>
      <div class="text-sm text-muted mt-4">
        <strong>BUYD</strong> = dollar-amount buy (broker dollar-based style)<br>
        <strong>BUY</strong> = share-count buy<br>
        <strong>SELL</strong> = sell by shares
      </div>
    </div>

    <form method="POST" action="/submit">
      <div class="form-group">
        <label class="form-label">Trades</label>
        <textarea name="fills" class="form-input" rows="8" placeholder="BUYD, JNJ, 100.00, 240.86"></textarea>
      </div>
      <div class="form-group">
        <label class="form-label">Set Cash Balance (optional override)</label>
        <input name="cash_set" class="form-input" type="number" step="0.01" placeholder="e.g. 202.27">
        <div class="form-hint">Sets cash to this exact value BEFORE applying trades. Current: <strong>${cash:.2f}</strong></div>
      </div>
      <button type="submit" class="btn btn-primary btn-block btn-lg">Submit Trades</button>
    </form>
  </div>

  <div class="card">
    <div class="card-title">Recent Fills</div>
    {_recent_fills_html(e)}
  </div>
</div>
"""
    return Response(page("Record Trades", content, "record"), mimetype="text/html")


def _recent_fills_html(e) -> str:
    try:
        with e.begin() as conn:
            fills = conn.execute(text("""
                SELECT fill_time_utc, symbol, side, shares, price, fees
                FROM fills ORDER BY id DESC LIMIT 20
            """)).fetchall()
    except Exception:
        return '<p class="text-muted text-sm">No fills recorded yet.</p>'

    if not fills:
        return '<p class="text-muted text-sm">No fills recorded yet.</p>'

    html = (
        '<div class="tbl-scroll">'
        '<table class="tbl"><thead><tr>'
        '<th>Date</th><th>Sym</th><th>Side</th>'
        '<th class="r">Shares</th><th class="r">Price</th><th class="r">Value</th>'
        '</tr></thead><tbody>'
    )
    for ts, sym, side, sh, px, fees in fills:
        date_short = ts[:10]
        side_class = "pos" if side == "BUY" else "neg"
        val = float(sh) * float(px)
        html += (
            f'<tr>'
            f'<td class="text-muted text-sm">{date_short}</td>'
            f'<td><span class="sym">{sym}</span></td>'
            f'<td class="{side_class}">{side}</td>'
            f'<td class="r">{float(sh):.4f}</td>'
            f'<td class="r">${float(px):.2f}</td>'
            f'<td class="r">${val:.2f}</td>'
            f'</tr>'
        )
    html += '</tbody></table></div>'
    return html


@app.post("/submit")
def submit():
    if not _check_auth(): return _unauth()

    raw = request.form.get("fills", "")
    cash_set = (request.form.get("cash_set", "") or "").strip()

    fills = []
    errors = []
    for i, line in enumerate(raw.splitlines()):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            errors.append(f"Line {i+1}: need at least ACTION,SYMBOL,AMOUNT,PRICE")
            continue
        try:
            fills.append((
                parts[0].upper(),
                parts[1].upper(),
                float(parts[2]),
                float(parts[3]),
                float(parts[4]) if len(parts) >= 5 and parts[4] else 0.0,
            ))
        except ValueError as e:
            errors.append(f"Line {i+1}: {e}")

    if errors and not fills and not cash_set:
        return Response("Errors:\n" + "\n".join(errors), mimetype="text/plain")

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    e = engine()

    with e.begin() as conn:
        if cash_set:
            set_cash(conn, float(cash_set))

        for action, sym, qty, px, fees in fills:
            if action in ("BUYD", "BUY"):
                if action == "BUYD":
                    dollars = float(qty)
                    shares = dollars / px
                else:
                    shares = float(qty)
                    dollars = shares * px

                prev = conn.execute(text(
                    "SELECT shares, avg_cost FROM holdings WHERE symbol=:s"
                ), {"s": sym}).fetchone()
                prev_sh = float(prev[0]) if prev else 0.0
                prev_ac = float(prev[1]) if prev else 0.0

                new_sh = prev_sh + shares
                new_ac = ((prev_sh * prev_ac) + (shares * px)) / new_sh if new_sh > 0 else 0.0

                conn.execute(text("""
                    INSERT INTO holdings(symbol, shares, avg_cost)
                    VALUES (:s, :sh, :ac)
                    ON CONFLICT(symbol) DO UPDATE SET shares=excluded.shares, avg_cost=excluded.avg_cost
                """), {"s": sym, "sh": new_sh, "ac": new_ac})

                conn.execute(text("""
                    INSERT INTO fills(fill_time_utc, symbol, side, shares, price, fees)
                    VALUES (:t, :s, 'BUY', :sh, :px, :fees)
                """), {"t": now_utc, "s": sym, "sh": shares, "px": px, "fees": fees})

                conn.execute(text("""
                    INSERT INTO lots(symbol, buy_time_utc, shares_remaining, cost_per_share)
                    VALUES (:s, :t, :sh, :cps)
                """), {"s": sym, "t": now_utc, "sh": shares, "cps": px})

                cash = get_cash(conn)
                set_cash(conn, cash - dollars - fees)

            elif action == "SELL":
                shares = float(qty)
                dollars = shares * px

                prev = conn.execute(text(
                    "SELECT shares, avg_cost FROM holdings WHERE symbol=:s"
                ), {"s": sym}).fetchone()
                prev_sh = float(prev[0]) if prev else 0.0
                prev_ac = float(prev[1]) if prev else 0.0

                new_sh = max(0.0, prev_sh - shares)
                conn.execute(text("""
                    INSERT INTO holdings(symbol, shares, avg_cost)
                    VALUES (:s, :sh, :ac)
                    ON CONFLICT(symbol) DO UPDATE SET shares=excluded.shares, avg_cost=excluded.avg_cost
                """), {"s": sym, "sh": new_sh, "ac": prev_ac})

                conn.execute(text("""
                    INSERT INTO fills(fill_time_utc, symbol, side, shares, price, fees)
                    VALUES (:t, :s, 'SELL', :sh, :px, :fees)
                """), {"t": now_utc, "s": sym, "sh": shares, "px": px, "fees": fees})

                remaining = shares
                lots = conn.execute(text("""
                    SELECT lot_id, shares_remaining FROM lots
                    WHERE symbol=:s AND shares_remaining > 0
                    ORDER BY buy_time_utc ASC, lot_id ASC
                """), {"s": sym}).fetchall()
                for lot_id, lot_sh in lots:
                    if remaining <= 1e-12: break
                    take = min(float(lot_sh), remaining)
                    conn.execute(text("UPDATE lots SET shares_remaining = shares_remaining - :t WHERE lot_id=:id"),
                                 {"t": take, "id": int(lot_id)})
                    remaining -= take

                cash = get_cash(conn)
                set_cash(conn, cash + dollars - fees)

        log_action(conn, "submit_fills", f"{len(fills)} fills at {now_utc}")

    return redirect("/record?success=1")


@app.get("/performance")
def performance():
    if not _check_auth(): return _unauth()

    e = engine()
    with e.begin() as conn:
        nav_rows = conn.execute(text("""
            SELECT asof_date, total_value, total_cost, unrealized_pnl, spy_close
            FROM nav_history
            ORDER BY asof_date ASC
        """)).fetchall()

    if len(nav_rows) < 2:
        content = """
<div class="page-header">
  <div class="page-title">Performance</div>
  <div class="page-sub">Portfolio vs S&amp;P 500 over time</div>
</div>
<div class="card">
  <div class="alert alert-info">
    Performance tracking will appear here once you have at least 2 days of NAV history.
    The cron job records NAV daily — check back tomorrow.
  </div>
</div>"""
        return Response(page("Performance", content, "performance"), mimetype="text/html")

    dates = [r[0] for r in nav_rows]
    values = [float(r[1]) for r in nav_rows]
    costs = [float(r[2]) for r in nav_rows]
    spy = [float(r[4]) if r[4] else None for r in nav_rows]

    v0 = values[0] if values[0] > 0 else 1
    s0 = spy[0] if spy[0] else None

    port_norm = [v / v0 * 100 for v in values]
    spy_norm = [(s / s0 * 100 if s and s0 else None) for s in spy]

    latest_val = values[-1]
    latest_cost = costs[-1]
    total_gl = latest_val - latest_cost
    gl_pct = (total_gl / latest_cost * 100) if latest_cost > 0 else 0
    gl_class = "stat-up" if total_gl >= 0 else "stat-down"
    gl_sign = "+" if total_gl >= 0 else ""

    spy_perf = ""
    if s0 and spy[-1]:
        spy_gl = (spy[-1] / s0 - 1) * 100
        spy_sign = "+" if spy_gl >= 0 else ""
        spy_perf = f"{spy_sign}{spy_gl:.1f}%"

    port_perf = f"{gl_sign}{gl_pct:.1f}%"

    content = f"""
<div class="page-header">
  <div class="page-title">Performance</div>
  <div class="page-sub">Portfolio vs S&amp;P 500 (SPY) — since inception</div>
</div>

<div class="stat-grid">
  <div class="stat-tile">
    <div class="stat-label">Portfolio Return</div>
    <div class="stat-value {gl_class}">{port_perf}</div>
    <div class="stat-sub">{gl_sign}${total_gl:,.2f} total</div>
  </div>
  <div class="stat-tile">
    <div class="stat-label">SPY Return (same period)</div>
    <div class="stat-value">{spy_perf or "N/A"}</div>
    <div class="stat-sub text-muted">S&amp;P 500 benchmark</div>
  </div>
  <div class="stat-tile">
    <div class="stat-label">Current Value</div>
    <div class="stat-value">${latest_val:,.2f}</div>
    <div class="stat-sub text-muted">as of {dates[-1]}</div>
  </div>
  <div class="stat-tile">
    <div class="stat-label">Total Invested</div>
    <div class="stat-value">${latest_cost:,.2f}</div>
    <div class="stat-sub text-muted">cost basis</div>
  </div>
</div>

<div class="card">
  <div class="card-title">Portfolio vs SPY (Indexed to 100)</div>
  <canvas id="perfChart" height="80"></canvas>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
const labels = {json.dumps(dates)};
const portData = {json.dumps(port_norm)};
const spyData = {json.dumps(spy_norm)};

const ctx = document.getElementById('perfChart').getContext('2d');
new Chart(ctx, {{
  type: 'line',
  data: {{
    labels,
    datasets: [
      {{
        label: 'Alpha Portfolio',
        data: portData,
        borderColor: '#3b82f6',
        backgroundColor: 'rgba(59,130,246,0.08)',
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.3,
        fill: true,
      }},
      {{
        label: 'SPY',
        data: spyData,
        borderColor: '#64748b',
        backgroundColor: 'transparent',
        borderWidth: 1.5,
        borderDash: [4,3],
        pointRadius: 0,
        tension: 0.3,
      }},
    ]
  }},
  options: {{
    responsive: true,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 12 }} }} }},
      tooltip: {{
        backgroundColor: '#111827',
        borderColor: '#1f2d45',
        borderWidth: 1,
        titleColor: '#e2e8f0',
        bodyColor: '#94a3b8',
        callbacks: {{
          label: ctx => ` ${{ctx.dataset.label}}: ${{ctx.parsed.y.toFixed(1)}}`,
        }}
      }}
    }},
    scales: {{
      x: {{
        ticks: {{ color: '#64748b', maxTicksLimit: 8, font: {{ size: 11 }} }},
        grid: {{ color: 'rgba(31,45,69,0.5)' }},
      }},
      y: {{
        ticks: {{ color: '#64748b', callback: v => v.toFixed(0), font: {{ size: 11 }} }},
        grid: {{ color: 'rgba(31,45,69,0.5)' }},
      }}
    }}
  }}
}});
</script>
"""
    return Response(page("Performance", content, "performance"), mimetype="text/html")


@app.get("/admin")
def admin():
    if not _check_auth(): return _unauth()

    e = engine()
    with e.begin() as conn:
        price_date = conn.execute(text("SELECT MAX(date) FROM prices_daily")).fetchone()[0] or "Never"
        score_date = conn.execute(text("SELECT MAX(run_date) FROM scores")).fetchone()[0] or "Never"
        universe_n = conn.execute(text("SELECT COUNT(*) FROM universe")).fetchone()[0]
        excl_n = conn.execute(text("SELECT COUNT(*) FROM universe_exclusions")).fetchone()[0]
        next_reb = get_meta(conn, "next_rebalance_date") or "Not set"

        cron_rows = conn.execute(text("""
            SELECT run_date, status, steps_completed, error_message
            FROM cron_runs ORDER BY id DESC LIMIT 10
        """)).fetchall()

        log_rows = conn.execute(text("""
            SELECT timestamp_utc, action, details, success, error_message
            FROM admin_log ORDER BY id DESC LIMIT 15
        """)).fetchall()

    cron_html = ""
    for run_date, status, steps, err in cron_rows:
        cls = "ok" if status == "ok" else "fail" if "fail" in status else "warn"
        icon = "✓" if cls == "ok" else "✗" if cls == "fail" else "⚠"
        cron_html += f'<div class="log-entry {cls}"><span style="color:var(--muted)">{run_date}</span> &nbsp; {icon} {status} &nbsp; <span style="color:var(--muted)">{steps or ""}</span>'
        if err:
            cron_html += f'<br><span style="color:var(--red);font-size:11px">{err[:200]}</span>'
        cron_html += '</div>'

    log_html = ""
    for ts, action, details, success, err in log_rows:
        cls = "ok" if success else "fail"
        icon = "✓" if success else "✗"
        log_html += f'<div class="log-entry {cls}"><span style="color:var(--muted)">{ts[:16]}</span> &nbsp; {icon} {action}'
        if details:
            log_html += f': <span style="color:var(--text)">{details[:100]}</span>'
        log_html += '</div>'

    content = f"""
<div class="page-header">
  <div class="page-title">Admin</div>
  <div class="page-sub">System status, data management, and controls</div>
</div>

<div class="stat-grid">
  <div class="stat-tile"><div class="stat-label">Last Price Update</div><div class="stat-value" style="font-size:16px">{price_date}</div></div>
  <div class="stat-tile"><div class="stat-label">Last Score Run</div><div class="stat-value" style="font-size:16px">{score_date}</div></div>
  <div class="stat-tile"><div class="stat-label">Universe</div><div class="stat-value">{universe_n}</div><div class="stat-sub text-muted">{excl_n} excluded</div></div>
  <div class="stat-tile"><div class="stat-label">Next Rebalance</div><div class="stat-value" style="font-size:16px">{next_reb}</div></div>
</div>

<div class="grid-2">
  <div>
    <div class="card">
      <div class="card-title">Quick Actions</div>
      <div style="display:flex;flex-direction:column;gap:10px">
        <form method="POST" action="/admin/refresh-prices">
          <button class="btn btn-ghost btn-block">Refresh Stock Prices</button>
        </form>
        <form method="POST" action="/admin/refresh-scores">
          <button class="btn btn-ghost btn-block">Recalculate Scores</button>
        </form>
        <form method="POST" action="/admin/force-rebalance">
          <button class="btn btn-success btn-block">Generate Trade Plan Now</button>
        </form>
        <form method="POST" action="/admin/update-universe">
          <button class="btn btn-ghost btn-block">Update S&amp;P 500 Universe</button>
        </form>
        <form method="POST" action="/admin/backfill-prices">
          <button class="btn btn-ghost btn-block">Backfill Price History</button>
        </form>
        <hr>
        <a href="/admin/reset-portfolio" class="btn btn-danger btn-block">Reset / Seed Portfolio</a>
      </div>
    </div>
  </div>

  <div>
    <div class="card">
      <div class="card-title">Cron Run History</div>
      {cron_html or '<p class="text-muted text-sm">No cron runs recorded yet.</p>'}
    </div>

    <div class="card">
      <div class="card-title">Admin Activity Log</div>
      {log_html or '<p class="text-muted text-sm">No activity yet.</p>'}
    </div>
  </div>
</div>
"""
    return Response(page("Admin", content, "admin"), mimetype="text/html")


@app.get("/admin/reset-portfolio")
def reset_portfolio_form():
    if not _check_auth(): return _unauth()

    default_fills = """# Paste your holdings below. One per line:
# SYMBOL, SHARES, AVG_COST_PER_SHARE, BUY_DATE (YYYY-MM-DD)
# Example:
# JNJ, 0.245, 242.12, 2026-02-13
"""

    content = f"""
<div class="page-header">
  <div class="page-title">Reset / Seed Portfolio</div>
  <div class="page-sub">Wipe and re-enter your actual holdings</div>
</div>

<div class="alert alert-warning">
  <strong>Warning:</strong> This will completely replace all holdings, lots, and fills.
  Your price history and scores will be preserved.
</div>

<div class="card">
  <div class="card-title">Holdings</div>
  <p class="text-muted text-sm mb-4">
    Enter each position from your brokerage account. Use the <strong>Average Cost Basis</strong>
    from your broker's Positions page. For multiple lots (bought on different dates), enter separate lines.
  </p>

  <form method="POST" action="/admin/reset-portfolio">
    <div class="form-group">
      <label class="form-label">Holdings (one per line)</label>
      <textarea name="holdings" class="form-input" rows="20">{default_fills}</textarea>
      <div class="form-hint">Format: SYMBOL, SHARES, AVG_COST, DATE</div>
    </div>

    <div class="form-group">
      <label class="form-label">Cash Balance ($)</label>
      <input name="cash" class="form-input" type="number" step="0.01" placeholder="202.27" required>
      <div class="form-hint">Your current cash balance</div>
    </div>

    <div class="form-group">
      <label class="form-label">Confirm Reset</label>
      <input name="confirm" class="form-input" placeholder='Type "RESET" to confirm'>
    </div>

    <button type="submit" class="btn btn-danger btn-lg">Reset Portfolio</button>
    <a href="/admin" class="btn btn-ghost btn-lg" style="margin-left:10px">Cancel</a>
  </form>
</div>
"""
    return Response(page("Reset Portfolio", content, "admin"), mimetype="text/html")


@app.post("/admin/reset-portfolio")
def reset_portfolio():
    if not _check_auth(): return _unauth()

    confirm = request.form.get("confirm", "").strip()
    if confirm != "RESET":
        return Response("Type RESET to confirm.", mimetype="text/plain", status=400)

    raw = request.form.get("holdings", "")
    cash_str = request.form.get("cash", "0")

    holdings_data = []
    errors = []
    for i, line in enumerate(raw.splitlines()):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            errors.append(f"Line {i+1}: need SYMBOL,SHARES,AVG_COST,DATE")
            continue
        try:
            holdings_data.append({
                "symbol": parts[0].upper(),
                "shares": float(parts[1]),
                "avg_cost": float(parts[2]),
                "date": parts[3],
            })
        except ValueError as e:
            errors.append(f"Line {i+1}: {e}")

    if errors:
        return Response("Errors:\n" + "\n".join(errors), mimetype="text/plain", status=400)

    try:
        cash = float(cash_str)
    except ValueError:
        return Response("Invalid cash amount", mimetype="text/plain", status=400)

    e = engine()
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    with e.begin() as conn:
        conn.execute(text("DELETE FROM holdings"))
        conn.execute(text("DELETE FROM lots"))
        conn.execute(text("DELETE FROM fills"))

        set_cash(conn, cash)

        by_symbol = {}
        for h in holdings_data:
            sym = h["symbol"]
            if sym not in by_symbol:
                by_symbol[sym] = {"total_shares": 0.0, "total_cost": 0.0, "lots": []}
            by_symbol[sym]["total_shares"] += h["shares"]
            by_symbol[sym]["total_cost"] += h["shares"] * h["avg_cost"]
            by_symbol[sym]["lots"].append(h)

        for sym, data in by_symbol.items():
            avg_cost = data["total_cost"] / data["total_shares"] if data["total_shares"] > 0 else 0.0
            conn.execute(text("""
                INSERT INTO holdings(symbol, shares, avg_cost)
                VALUES (:s, :sh, :ac)
                ON CONFLICT(symbol) DO UPDATE SET shares=excluded.shares, avg_cost=excluded.avg_cost
            """), {"s": sym, "sh": data["total_shares"], "ac": avg_cost})

            for lot in data["lots"]:
                buy_utc = lot["date"] + " 09:30:00"
                conn.execute(text("""
                    INSERT INTO lots(symbol, buy_time_utc, shares_remaining, cost_per_share)
                    VALUES (:s, :t, :sh, :cps)
                """), {"s": sym, "t": buy_utc, "sh": lot["shares"], "cps": lot["avg_cost"]})

                conn.execute(text("""
                    INSERT INTO fills(fill_time_utc, symbol, side, shares, price, fees)
                    VALUES (:t, :s, 'BUY', :sh, :px, 0.0)
                """), {"t": buy_utc, "s": sym, "sh": lot["shares"], "px": lot["avg_cost"]})

        log_action(conn, "reset_portfolio",
                   f"{len(by_symbol)} symbols, ${cash:.2f} cash, {len(holdings_data)} lots")

    return redirect("/admin?reset=1")


@app.get("/settings")
def settings():
    if not _check_auth(): return _unauth()

    e = engine()
    with e.begin() as conn:
        next_reb = get_meta(conn, "next_rebalance_date") or "—"
        default_contrib = get_meta(conn, "default_contribution") or "0"
        cash = get_cash(conn)

    content = f"""
<div class="page-header">
  <div class="page-title">Settings</div>
  <div class="page-sub">Configure contribution amounts and schedule</div>
</div>

<div class="grid-2">
  <div class="card">
    <div class="card-title">Biweekly Contribution</div>
    <p class="text-muted text-sm mb-4">
      This is the amount you transfer to your broker each payday.
      It's added to your cash before computing buys on rebalance day.
    </p>
    <form method="POST" action="/settings/contribution">
      <div class="form-group">
        <label class="form-label">Contribution Amount ($)</label>
        <input name="amount" class="form-input" type="number" step="0.01"
               value="{default_contrib}" placeholder="e.g. 200">
        <div class="form-hint">Current setting: <strong>${float(default_contrib):.2f}</strong></div>
      </div>
      <button type="submit" class="btn btn-primary">Save</button>
    </form>
  </div>

  <div class="card">
    <div class="card-title">Schedule Info</div>
    <div class="text-sm">
      <div style="padding:10px 0;border-bottom:1px solid var(--border)">
        <span class="text-muted">Next Rebalance</span>
        <div style="font-family:var(--mono);font-size:16px;margin-top:4px">{next_reb}</div>
      </div>
      <div style="padding:10px 0;border-bottom:1px solid var(--border)">
        <span class="text-muted">Cadence</span>
        <div style="margin-top:4px">Every other Friday</div>
      </div>
      <div style="padding:10px 0">
        <span class="text-muted">Current Cash</span>
        <div style="font-family:var(--mono);font-size:16px;margin-top:4px">${cash:.2f}</div>
      </div>
    </div>
    <div class="alert alert-info mt-4" style="margin-bottom:0">
      On rebalance day, contribution is added to cash before buys are calculated.
      Make sure you've transferred the money to your broker before executing trades.
    </div>
  </div>
</div>
"""
    return Response(page("Settings", content, "settings"), mimetype="text/html")


@app.post("/settings/contribution")
def settings_contribution():
    if not _check_auth(): return _unauth()
    amount = float(request.form.get("amount", "0"))
    e = engine()
    with e.begin() as conn:
        set_meta(conn, "default_contribution", str(amount))
        conn.execute(text("""
            INSERT INTO contribution_schedule(effective_date, amount)
            VALUES (date('now'), :a)
            ON CONFLICT(effective_date) DO UPDATE SET amount=excluded.amount
        """), {"a": amount})
        log_action(conn, "set_contribution", f"${amount:.2f}")
    return redirect("/settings")


# ─── Admin actions ───

def _admin_action(module: str, label: str, timeout: int = 600):
    if not _check_auth(): return _unauth()
    success, stdout, stderr = run_script(*module.split(), timeout=timeout)
    e = engine()
    with e.begin() as conn:
        log_action(conn, label, stdout[:300], success=success, error=stderr[:300])
    out = stdout + ("\n\nErrors:\n" + stderr if stderr else "")
    status = 200 if success else 500
    return Response(f"{'OK' if success else 'FAILED'} {label}\n\n{out}", mimetype="text/plain", status=status)


@app.post("/admin/refresh-prices")
def admin_refresh_prices():
    return _admin_action("src.ingest_prices", "refresh_prices")

@app.post("/admin/refresh-scores")
def admin_refresh_scores():
    return _admin_action("src.score_universe", "refresh_scores", timeout=120)

@app.post("/admin/force-rebalance")
def admin_force_rebalance():
    if not _check_auth(): return _unauth()
    python = VENV_PYTHON if Path(VENV_PYTHON).exists() else "python3"
    try:
        result = subprocess.run(
            [python, "-m", "src.rebalance", "--force"],
            capture_output=True, text=True, timeout=300, cwd=str(PROJECT_ROOT)
        )
        success = result.returncode == 0
        out = result.stdout + ("\n\nErrors:\n" + result.stderr if result.stderr else "")
        e = engine()
        with e.begin() as conn:
            log_action(conn, "force_rebalance", result.stdout[:300],
                       success=success, error=result.stderr[:300])
        return redirect("/plan")
    except Exception as ex:
        return Response(f"Error: {ex}", mimetype="text/plain", status=500)

@app.post("/admin/update-universe")
def admin_update_universe():
    return _admin_action("src.update_universe_sp500", "update_universe", timeout=60)

@app.post("/admin/backfill-prices")
def admin_backfill_prices():
    return _admin_action("src.ingest_prices --backfill", "backfill_prices", timeout=1200)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=False)
