"""
Paper trading engine with SQLite persistence.

Two tables:
  paper_trades     — every trade opened/closed by the user
  signal_feedback  — feature snapshot + outcome for ML retraining
"""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "trades.db"
DB_PATH.parent.mkdir(exist_ok=True)


# ── DB connection ─────────────────────────────────────────────────────────────

@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


# ── Schema ────────────────────────────────────────────────────────────────────

def init_db():
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS paper_trades (
                id              TEXT PRIMARY KEY,
                symbol          TEXT NOT NULL,
                instrument_key  TEXT,
                signal          TEXT NOT NULL,
                entry           REAL NOT NULL,
                target          REAL,
                stop_loss       REAL,
                entry_time      TEXT NOT NULL,
                exit_price      REAL,
                exit_time       TEXT,
                status          TEXT NOT NULL DEFAULT 'OPEN',
                pnl             REAL,
                pnl_pct         REAL,
                type            TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS signal_feedback (
                id              TEXT PRIMARY KEY,
                trade_id        TEXT NOT NULL,
                symbol          TEXT NOT NULL,
                instrument_key  TEXT,
                trade_type      TEXT NOT NULL,
                signal          TEXT NOT NULL,
                features_json   TEXT,
                outcome         INTEGER,
                created_at      TEXT NOT NULL,
                resolved_at     TEXT,
                FOREIGN KEY (trade_id) REFERENCES paper_trades(id)
            );
        """)


init_db()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row(d) -> dict:
    return dict(d)


def _pnl(signal: str, entry: float, exit_price: float):
    raw = (exit_price - entry) if signal == "BUY" else (entry - exit_price)
    pct = (raw / entry) * 100 if entry else 0
    return round(raw, 2), round(pct, 2)


def _hit_status(signal: str, exit_price: float, target, stop_loss) -> str:
    if signal == "BUY":
        if target and exit_price >= target:
            return "TARGET_HIT"
        if stop_loss and exit_price <= stop_loss:
            return "SL_HIT"
    else:
        if target and exit_price <= target:
            return "TARGET_HIT"
        if stop_loss and exit_price >= stop_loss:
            return "SL_HIT"
    return "MANUAL_EXIT"


# ── Write API ─────────────────────────────────────────────────────────────────

def add_trade(
    symbol: str,
    signal: str,
    entry: float,
    target: float,
    stop_loss: float,
    trade_type: str,
    instrument_key: str = None,
    features_snapshot: dict = None,
) -> dict:
    trade_id = str(uuid.uuid4())
    now = datetime.now().isoformat()

    with _conn() as con:
        con.execute(
            """INSERT INTO paper_trades
               (id, symbol, instrument_key, signal, entry, target, stop_loss,
                entry_time, status, type)
               VALUES (?,?,?,?,?,?,?,?,'OPEN',?)""",
            (trade_id, symbol, instrument_key, signal, entry, target, stop_loss, now, trade_type),
        )

        features_json = json.dumps(features_snapshot) if features_snapshot else None
        con.execute(
            """INSERT INTO signal_feedback
               (id, trade_id, symbol, instrument_key, trade_type, signal,
                features_json, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), trade_id, symbol, instrument_key,
             trade_type, signal, features_json, now),
        )

    return get_trade(trade_id)


def exit_trade(trade_id: str, exit_price: float) -> dict:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM paper_trades WHERE id=?", (trade_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Trade {trade_id} not found")

        trade = _row(row)
        if trade["status"] != "OPEN":
            raise ValueError(f"Trade {trade_id} is already closed")

        status = _hit_status(trade["signal"], exit_price, trade["target"], trade["stop_loss"])
        pnl, pnl_pct = _pnl(trade["signal"], trade["entry"], exit_price)
        now = datetime.now().isoformat()

        con.execute(
            """UPDATE paper_trades
               SET exit_price=?, exit_time=?, status=?, pnl=?, pnl_pct=?
               WHERE id=?""",
            (exit_price, now, status, pnl, pnl_pct, trade_id),
        )

        # TARGET_HIT = model was right (1), SL_HIT = model was wrong (0)
        outcome = 1 if status == "TARGET_HIT" else (0 if status == "SL_HIT" else None)
        con.execute(
            "UPDATE signal_feedback SET outcome=?, resolved_at=? WHERE trade_id=?",
            (outcome, now, trade_id),
        )

    return get_trade(trade_id)


# ── Read API ──────────────────────────────────────────────────────────────────

def get_trade(trade_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM paper_trades WHERE id=?", (trade_id,)
        ).fetchone()
        return _row(row) if row else None


def get_all_trades() -> list:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM paper_trades ORDER BY entry_time DESC"
        ).fetchall()
        return [_row(r) for r in rows]


def get_open_trades() -> list:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM paper_trades WHERE status='OPEN'"
        ).fetchall()
        return [_row(r) for r in rows]


def get_summary() -> dict:
    with _conn() as con:
        all_t = con.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
        open_t = con.execute(
            "SELECT COUNT(*) FROM paper_trades WHERE status='OPEN'"
        ).fetchone()[0]
        closed = con.execute(
            "SELECT pnl FROM paper_trades WHERE status != 'OPEN' AND pnl IS NOT NULL"
        ).fetchall()

    closed_pnl = [r[0] for r in closed]
    winners = [p for p in closed_pnl if p > 0]
    total_pnl = round(sum(closed_pnl), 2) if closed_pnl else 0
    win_rate = round(len(winners) / len(closed_pnl) * 100, 2) if closed_pnl else 0

    return {
        "total_trades": all_t,
        "open_trades": open_t,
        "winners": len(winners),
        "losers": len(closed_pnl) - len(winners),
        "total_pnl": total_pnl,
        "win_rate": win_rate,
    }


# ── Feedback API ──────────────────────────────────────────────────────────────

def get_feedback_samples(trade_type: str = None) -> list:
    """Return all resolved feedback rows with parsed feature dicts."""
    with _conn() as con:
        q = """SELECT sf.* FROM signal_feedback sf
               WHERE sf.outcome IS NOT NULL
               AND sf.features_json IS NOT NULL"""
        params = []
        if trade_type:
            q += " AND sf.trade_type=?"
            params.append(trade_type)
        rows = con.execute(q, params).fetchall()

    result = []
    for r in rows:
        d = _row(r)
        d["features"] = json.loads(d["features_json"])
        result.append(d)
    return result


def get_feedback_stats() -> dict:
    with _conn() as con:
        total = con.execute(
            "SELECT COUNT(*) FROM signal_feedback WHERE outcome IS NOT NULL"
        ).fetchone()[0]
        correct = con.execute(
            "SELECT COUNT(*) FROM signal_feedback WHERE outcome=1"
        ).fetchone()[0]
        intraday = con.execute(
            "SELECT COUNT(*) FROM signal_feedback WHERE outcome IS NOT NULL AND trade_type='INTRADAY'"
        ).fetchone()[0]
        swing = con.execute(
            "SELECT COUNT(*) FROM signal_feedback WHERE outcome IS NOT NULL AND trade_type='SWING'"
        ).fetchone()[0]

    return {
        "total": total,
        "correct": correct,
        "wrong": total - correct,
        "model_win_rate": round(correct / total * 100, 1) if total else None,
        "intraday_samples": intraday,
        "swing_samples": swing,
        "ready_to_retrain": total >= 10,
    }


# ── Legacy compatibility ───────────────────────────────────────────────────────

def check_and_update_trades(current_prices: dict) -> list:
    """Auto-exit open trades when price hits target or SL."""
    updated = []
    open_trades = get_open_trades()
    for trade in open_trades:
        price = current_prices.get(trade["symbol"])
        if price is None:
            continue
        status = _hit_status(trade["signal"], price, trade["target"], trade["stop_loss"])
        if status != "MANUAL_EXIT":
            updated.append(exit_trade(trade["id"], price))
    return updated
