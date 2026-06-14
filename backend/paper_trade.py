import uuid
from datetime import datetime

trades: list = []


def add_trade(symbol: str, signal: str, entry: float, target: float, stop_loss: float, trade_type: str) -> dict:
    trade = {
        "id": str(uuid.uuid4()),
        "symbol": symbol,
        "signal": signal,
        "entry": entry,
        "target": target,
        "stop_loss": stop_loss,
        "entry_time": datetime.now().isoformat(),
        "exit_price": None,
        "exit_time": None,
        "status": "OPEN",
        "pnl": None,
        "pnl_pct": None,
        "type": trade_type,
    }
    trades.append(trade)
    return trade


def _calculate_pnl(trade: dict, exit_price: float):
    if trade["signal"] == "BUY":
        pnl = exit_price - trade["entry"]
    else:
        pnl = trade["entry"] - exit_price

    pnl_pct = (pnl / trade["entry"]) * 100 if trade["entry"] else 0
    return round(pnl, 2), round(pnl_pct, 2)


def exit_trade(trade_id: str, exit_price: float) -> dict:
    trade = next((t for t in trades if t["id"] == trade_id), None)
    if trade is None:
        raise ValueError(f"Trade {trade_id} not found")

    pnl, pnl_pct = _calculate_pnl(trade, exit_price)

    trade["exit_price"] = exit_price
    trade["exit_time"] = datetime.now().isoformat()
    trade["status"] = "MANUAL_EXIT"
    trade["pnl"] = pnl
    trade["pnl_pct"] = pnl_pct

    return trade


def get_all_trades() -> list:
    return trades


def get_open_trades() -> list:
    return [t for t in trades if t["status"] == "OPEN"]


def get_summary() -> dict:
    closed_trades = [t for t in trades if t["status"] != "OPEN"]
    winners = [t for t in closed_trades if (t["pnl"] or 0) > 0]
    losers = [t for t in closed_trades if (t["pnl"] or 0) <= 0]
    total_pnl = sum(t["pnl"] or 0 for t in closed_trades)
    win_rate = round((len(winners) / len(closed_trades)) * 100, 2) if closed_trades else 0

    return {
        "total_trades": len(trades),
        "open_trades": len(get_open_trades()),
        "winners": len(winners),
        "losers": len(losers),
        "total_pnl": round(total_pnl, 2),
        "win_rate": win_rate,
    }


def check_and_update_trades(current_prices: dict) -> list:
    """
    current_prices: {symbol: current_price}
    Updates OPEN trades to TARGET_HIT or SL_HIT if the current price has crossed
    the trade's target or stop loss.
    """
    updated = []

    for trade in trades:
        if trade["status"] != "OPEN":
            continue

        price = current_prices.get(trade["symbol"])
        if price is None:
            continue

        hit_status = None
        if trade["signal"] == "BUY":
            if price >= trade["target"]:
                hit_status = "TARGET_HIT"
            elif price <= trade["stop_loss"]:
                hit_status = "SL_HIT"
        else:  # SELL
            if price <= trade["target"]:
                hit_status = "TARGET_HIT"
            elif price >= trade["stop_loss"]:
                hit_status = "SL_HIT"

        if hit_status:
            pnl, pnl_pct = _calculate_pnl(trade, price)
            trade["exit_price"] = price
            trade["exit_time"] = datetime.now().isoformat()
            trade["status"] = hit_status
            trade["pnl"] = pnl
            trade["pnl_pct"] = pnl_pct
            updated.append(trade)

    return updated
