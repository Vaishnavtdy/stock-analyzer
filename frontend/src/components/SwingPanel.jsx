import { useState } from "react";
import api from "../api";

function ModelBadge({ model }) {
  if (!model) return null;
  const isEnsemble = model === "ensemble";
  return (
    <span className={`model-badge ${isEnsemble ? "model-ensemble" : "model-xgb"}`}>
      {isEnsemble ? "BiLSTM + XGBoost" : "XGBoost"}
    </span>
  );
}

function ProbBar({ label, value, color }) {
  if (value == null) return null;
  const pct = Math.round(value * 100);
  return (
    <div className="prob-bar-row">
      <span className="prob-bar-label">{label}</span>
      <div className="prob-bar-track">
        <div className="prob-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="prob-bar-value" style={{ color }}>{pct}%</span>
    </div>
  );
}

function SwingPanel({ symbol, signal, prediction, featuresSnapshot, instrumentKey }) {
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
        instrument_key: instrumentKey,
        features_snapshot: featuresSnapshot,
      });
      setAdded(true);
      setTimeout(() => setAdded(false), 2000);
    } finally {
      setAdding(false);
    }
  };

  const isEnsemble = prediction?.model === "ensemble";

  return (
    <div className="panel swing-panel">
      <div className="panel-title-row">
        <h3>Swing Signal</h3>
        {prediction?.model && <ModelBadge model={prediction.model} />}
      </div>

      <div className="signal-meta">
        Horizon: <strong>{signal.horizon}</strong>
        {prediction && (
          <span>
            {" "}· ML predicts <strong>{prediction.direction}</strong> in {prediction.days} days
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
          <span className="label">Confidence</span>
          <span className="value">
            {prediction ? `${(prediction.prob_up * 100).toFixed(1)}% UP` : "--"}
          </span>
        </div>
      </div>

      {/* Ensemble model breakdown */}
      {isEnsemble && prediction && (
        <div className="ensemble-breakdown">
          <div className="ensemble-title">Model Breakdown</div>
          <ProbBar
            label="BiLSTM"
            value={prediction.bilstm_prob_up}
            color="#a78bfa"
          />
          <ProbBar
            label="XGBoost"
            value={prediction.xgb_prob_up}
            color="#4ade80"
          />
          <ProbBar
            label="Ensemble"
            value={prediction.prob_up}
            color="#facc15"
          />
        </div>
      )}

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
