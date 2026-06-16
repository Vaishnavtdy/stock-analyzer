import { useState } from "react";
import api from "../api";

function ScoreBar({ score, max = 14 }) {
  const pct = Math.min(100, Math.round((score / max) * 100));
  const color = score >= 9 ? "#4ade80" : score >= 6 ? "#facc15" : "#ef5350";
  return (
    <div className="score-bar-wrap">
      <div className="score-bar-track">
        <div className="score-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="score-bar-label" style={{ color }}>
        {score}/14
      </span>
    </div>
  );
}

function SuggestionCard({ result, onLoad }) {
  const { symbol, combined_score, intraday, swing } = result;
  const swingSig = swing.signal;
  const intradaySig = intraday.signal;

  return (
    <div className="suggestion-card">
      <div className="suggestion-header">
        <span className="suggestion-symbol">{symbol}</span>
        <span className={`signal-badge ${swingSig.signal.toLowerCase()}`}>{swingSig.signal}</span>
      </div>

      <ScoreBar score={combined_score} />

      <div className="suggestion-metrics">
        <div className="suggestion-metric">
          <span className="label">RSI</span>
          <span className="value">{intraday.indicators.rsi ?? "—"}</span>
        </div>
        <div className="suggestion-metric">
          <span className="label">vs VWAP</span>
          <span className={`value ${intraday.indicators.above_vwap ? "positive" : "negative"}`}>
            {intraday.indicators.above_vwap ? "Above" : "Below"}
          </span>
        </div>
        <div className="suggestion-metric">
          <span className="label">Intraday</span>
          <span className={`value signal-text-${intradaySig.signal.toLowerCase()}`}>
            {intradaySig.signal}
          </span>
        </div>
        <div className="suggestion-metric">
          <span className="label">ML Conf.</span>
          <span className="value">{swing.prediction.confidence ?? "—"}</span>
        </div>
      </div>

      {swingSig.entry != null && (
        <div className="suggestion-levels">
          <div className="suggestion-level">
            <span className="label">Entry</span>
            <span className="value">{swingSig.entry}</span>
          </div>
          <div className="suggestion-level">
            <span className="label">Target</span>
            <span className="value positive">{swingSig.target}</span>
          </div>
          <div className="suggestion-level">
            <span className="label">SL</span>
            <span className="value negative">{swingSig.stop_loss}</span>
          </div>
          {swingSig.risk_reward != null && (
            <div className="suggestion-level">
              <span className="label">R:R</span>
              <span className="value">{swingSig.risk_reward}</span>
            </div>
          )}
        </div>
      )}

      <button className="load-analyze-btn" onClick={() => onLoad(result)}>
        Load &amp; Analyze
      </button>
    </div>
  );
}

export default function MarketScanner({ onLoadInstrument }) {
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);

  const runScan = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.post("/api/market-scan", { max_results: 5 });
      setResults(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleLoad = (result) => {
    onLoadInstrument({ instrument_key: result.instrument_key, symbol: result.symbol });
  };

  return (
    <div className="panel scanner-panel">
      <div className="scanner-header">
        <h3>Market Scanner</h3>
        <div className="scanner-header-right">
          {results && !loading && (
            <span className="scanner-meta">
              {results.scanned}/{results.total} stocks analysed
            </span>
          )}
          <button className="scan-btn" onClick={runScan} disabled={loading}>
            {loading ? "Scanning..." : "Scan Nifty 50"}
          </button>
        </div>
      </div>

      {error && <div className="error-text" style={{ marginTop: "0.5rem" }}>{error}</div>}

      {loading && (
        <div className="scanner-loading">
          Analysing Nifty 50 stocks in parallel — this may take 20–40 seconds...
        </div>
      )}

      {!loading && results && (
        <div className="scanner-results">
          <div className="scanner-section">
            <div className="scanner-section-title buy-title">
              Top Buy Picks ({results.buy_suggestions.length})
            </div>
            {results.buy_suggestions.length === 0 ? (
              <div className="scanner-empty">No strong buy signals found right now</div>
            ) : (
              <div className="suggestions-grid">
                {results.buy_suggestions.map((r) => (
                  <SuggestionCard key={r.symbol} result={r} onLoad={handleLoad} />
                ))}
              </div>
            )}
          </div>

          <div className="scanner-section">
            <div className="scanner-section-title sell-title">
              Top Sell / Avoid Picks ({results.sell_suggestions.length})
            </div>
            {results.sell_suggestions.length === 0 ? (
              <div className="scanner-empty">No strong sell signals found right now</div>
            ) : (
              <div className="suggestions-grid">
                {results.sell_suggestions.map((r) => (
                  <SuggestionCard key={r.symbol} result={r} onLoad={handleLoad} />
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {!loading && !results && (
        <div className="scanner-placeholder">
          Click <strong>Scan Nifty 50</strong> to analyse all 40 stocks and get ranked buy/sell suggestions.
        </div>
      )}
    </div>
  );
}
