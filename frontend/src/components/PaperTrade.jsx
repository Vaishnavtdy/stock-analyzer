import { useEffect, useState } from "react";
import api from "../api";

function PaperTrade() {
  const [trades, setTrades] = useState([]);
  const [summary, setSummary] = useState(null);
  const [exitInputs, setExitInputs] = useState({});

  const load = async () => {
    try {
      const res = await api.get("/api/paper-trades");
      setTrades(res.data.trades || []);
      setSummary(res.data.summary || null);
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    load();
    const interval = setInterval(load, 15000);
    return () => clearInterval(interval);
  }, []);

  const handleExit = async (tradeId) => {
    const exitPrice = parseFloat(exitInputs[tradeId]);
    if (Number.isNaN(exitPrice)) return;

    await api.put(`/api/paper-trades/${tradeId}/exit`, { exit_price: exitPrice });
    setExitInputs((prev) => ({ ...prev, [tradeId]: "" }));
    load();
  };

  return (
    <div className="panel paper-trade">
      <h3>Paper Trades</h3>

      {summary && (
        <div className="paper-summary">
          <span>Total: {summary.total_trades}</span>
          <span>Open: {summary.open_trades}</span>
          <span>Win Rate: {summary.win_rate}%</span>
          <span className={summary.total_pnl >= 0 ? "positive" : "negative"}>
            P&L: {summary.total_pnl}
          </span>
        </div>
      )}

      <div className="trade-table">
        <div className="trade-row trade-header">
          <span>Symbol</span>
          <span>Type</span>
          <span>Signal</span>
          <span>Entry</span>
          <span>Target</span>
          <span>SL</span>
          <span>Status</span>
          <span>P&L</span>
          <span>Exit</span>
        </div>

        {trades.length === 0 && <div className="trade-row empty">No paper trades yet</div>}

        {trades.map((trade) => (
          <div className="trade-row" key={trade.id}>
            <span>{trade.symbol}</span>
            <span>{trade.type}</span>
            <span className={trade.signal === "BUY" ? "positive" : "negative"}>{trade.signal}</span>
            <span>{trade.entry}</span>
            <span>{trade.target}</span>
            <span>{trade.stop_loss}</span>
            <span>{trade.status}</span>
            <span className={trade.pnl >= 0 ? "positive" : "negative"}>{trade.pnl ?? "--"}</span>
            <span>
              {trade.status === "OPEN" ? (
                <span className="exit-control">
                  <input
                    type="number"
                    placeholder="price"
                    value={exitInputs[trade.id] || ""}
                    onChange={(e) =>
                      setExitInputs((prev) => ({ ...prev, [trade.id]: e.target.value }))
                    }
                  />
                  <button onClick={() => handleExit(trade.id)}>Exit</button>
                </span>
              ) : (
                "--"
              )}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default PaperTrade;
