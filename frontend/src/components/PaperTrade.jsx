import { useEffect, useState } from "react";
import api from "../api";

function FeedbackStats({ stats, onRetrain, retraining }) {
  if (!stats || stats.total === 0) return null;

  const winColor = stats.model_win_rate >= 55 ? "#4ade80" : stats.model_win_rate >= 45 ? "#facc15" : "#ef5350";

  return (
    <div className="feedback-stats">
      <div className="feedback-stats-title">ML Feedback Loop</div>
      <div className="feedback-stats-grid">
        <div className="feedback-stat">
          <span className="label">Samples</span>
          <span className="value">{stats.total}</span>
        </div>
        <div className="feedback-stat">
          <span className="label">Correct</span>
          <span className="value positive">{stats.correct}</span>
        </div>
        <div className="feedback-stat">
          <span className="label">Wrong</span>
          <span className="value negative">{stats.wrong}</span>
        </div>
        <div className="feedback-stat">
          <span className="label">Signal Acc.</span>
          <span className="value" style={{ color: winColor }}>
            {stats.model_win_rate != null ? `${stats.model_win_rate}%` : "--"}
          </span>
        </div>
      </div>

      <button
        className="retrain-btn"
        onClick={onRetrain}
        disabled={retraining || !stats.ready_to_retrain}
        title={!stats.ready_to_retrain ? `Need ${10 - stats.total} more closed trades to retrain` : ""}
      >
        {retraining
          ? "Retraining..."
          : stats.ready_to_retrain
          ? "Retrain on Feedback"
          : `Need ${10 - stats.total} more trades`}
      </button>
    </div>
  );
}

function PaperTrade() {
  const [trades, setTrades]       = useState([]);
  const [summary, setSummary]     = useState(null);
  const [stats, setStats]         = useState(null);
  const [exitInputs, setExitInputs] = useState({});
  const [retraining, setRetraining] = useState(false);
  const [retrainResult, setRetrainResult] = useState(null);

  const load = async () => {
    try {
      const [tradesRes, statsRes] = await Promise.all([
        api.get("/api/paper-trades"),
        api.get("/api/feedback-stats"),
      ]);
      setTrades(tradesRes.data.trades || []);
      setSummary(tradesRes.data.summary || null);
      setStats(statsRes.data);
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

  const handleRetrain = async () => {
    setRetraining(true);
    setRetrainResult(null);
    try {
      const res = await api.post("/api/train-feedback", {});
      setRetrainResult({ success: true, data: res.data });
    } catch (err) {
      setRetrainResult({ success: false, error: err.response?.data?.detail || err.message });
    } finally {
      setRetraining(false);
      load();
    }
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
            P&amp;L: {summary.total_pnl}
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
          <span>P&amp;L</span>
          <span>Exit</span>
        </div>

        {trades.length === 0 && (
          <div className="trade-row empty">No paper trades yet</div>
        )}

        {trades.map((trade) => (
          <div className="trade-row" key={trade.id}>
            <span>{trade.symbol}</span>
            <span>{trade.type}</span>
            <span className={trade.signal === "BUY" ? "positive" : "negative"}>
              {trade.signal}
            </span>
            <span>{trade.entry}</span>
            <span>{trade.target}</span>
            <span>{trade.stop_loss}</span>
            <span className={`status-${trade.status?.toLowerCase().replace("_", "-")}`}>
              {trade.status}
            </span>
            <span className={trade.pnl >= 0 ? "positive" : "negative"}>
              {trade.pnl ?? "--"}
            </span>
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
                trade.exit_price ?? "--"
              )}
            </span>
          </div>
        ))}
      </div>

      <FeedbackStats stats={stats} onRetrain={handleRetrain} retraining={retraining} />

      {retrainResult && (
        <div className={`retrain-result ${retrainResult.success ? "retrain-ok" : "retrain-err"}`}>
          {retrainResult.success ? (
            <>
              Model retrained on {retrainResult.data.feedback_used} trades.{" "}
              {Object.entries(retrainResult.data.results).map(([type, r]) =>
                r.status === "retrained"
                  ? ` ${type.toUpperCase()}: ${(r.feedback_accuracy * 100).toFixed(1)}% feedback accuracy.`
                  : ` ${type.toUpperCase()}: ${r.reason}.`
              )}
            </>
          ) : (
            retrainResult.error
          )}
        </div>
      )}
    </div>
  );
}

export default PaperTrade;
