import { useState } from "react";
import api from "../api";

function SwingPanel({ symbol, signal, prediction }) {
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState(false);

  if (!signal) {
    return <div className="panel swing-panel">Run an analysis to see the swing signal</div>;
  }

  const handleAddTrade = async () => {
    setAdding(true);
    try {
      await api.post("/api/paper-trades", {
        symbol,
        signal: signal.signal,
        entry: signal.entry,
        target: signal.target,
        stop_loss: signal.stop_loss,
        type: "SWING",
      });
      setAdded(true);
      setTimeout(() => setAdded(false), 2000);
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="panel swing-panel">
      <h3>Swing Signal</h3>
      <div className="signal-meta">
        Horizon: <strong>{signal.horizon}</strong>
        {prediction && (
          <span>
            {" "}
            · ML predicts <strong>{prediction.direction}</strong> in {prediction.days} days
          </span>
        )}
      </div>

      <div className={`signal-badge ${signal.signal.toLowerCase()}`}>{signal.signal}</div>

      <div className="signal-grid">
        <div>
          <span className="label">Entry</span>
          <span className="value">{signal.entry}</span>
        </div>
        <div>
          <span className="label">Target</span>
          <span className="value">{signal.target ?? "--"}</span>
        </div>
        <div>
          <span className="label">Stop Loss</span>
          <span className="value">{signal.stop_loss ?? "--"}</span>
        </div>
        <div>
          <span className="label">Risk:Reward</span>
          <span className="value">{signal.risk_reward ?? "--"}</span>
        </div>
        <div>
          <span className="label">Score</span>
          <span className="value">{signal.score} / 7</span>
        </div>
        <div>
          <span className="label">ML Confidence</span>
          <span className="value">
            {prediction ? `${(signal.ml_confidence * 100).toFixed(1)}%` : "--"}
          </span>
        </div>
      </div>

      <ul className="reasoning-list">
        {signal.reasoning.map((reason, idx) => (
          <li key={idx}>{reason}</li>
        ))}
      </ul>

      <button
        className="add-trade-btn"
        onClick={handleAddTrade}
        disabled={adding || signal.signal === "NEUTRAL"}
      >
        {added ? "Added!" : adding ? "Adding..." : "Add to Paper Trade"}
      </button>
    </div>
  );
}

export default SwingPanel;
