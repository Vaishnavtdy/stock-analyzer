import { useState } from "react";
import api from "../api";

function ScoreBar({ score, max = 14 }) {
  const pct   = Math.min(100, Math.round((score / max) * 100));
  const color = score >= 9 ? "#4ade80" : score >= 6 ? "#facc15" : "#ef5350";
  return (
    <div className="score-bar-wrap">
      <div className="score-bar-track">
        <div className="score-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="score-bar-label" style={{ color }}>{score}/14</span>
    </div>
  );
}

function MoversBadge({ movers }) {
  if (!movers?.length) return null;
  return (
    <div className="movers-strip">
      <span className="movers-label">Top movers →</span>
      {movers.map((m) => (
        <span key={m.symbol} className="mover-chip">
          {m.symbol}
          <span className="mover-pct"> +{m.change_pct}%</span>
        </span>
      ))}
    </div>
  );
}

function AIReport({ report, loading }) {
  if (!loading && !report) return null;

  // Parse **SYMBOL** bold markers into styled spans
  const renderLine = (line, idx) => {
    const parts = line.split(/(\*\*[^*]+\*\*)/g);
    return (
      <p key={idx} className="ai-report-line">
        {parts.map((part, i) =>
          part.startsWith("**") && part.endsWith("**")
            ? <strong key={i} className="ai-report-symbol">{part.slice(2, -2)}</strong>
            : part
        )}
      </p>
    );
  };

  return (
    <div className="ai-report-panel">
      <div className="ai-report-header">
        <span className="ai-report-icon">✦</span>
        <span className="ai-report-title">AI Market Report</span>
        {loading && <span className="ai-report-loading">Generating...</span>}
      </div>
      {report && (
        <div className="ai-report-body">
          {report.split("\n").filter(Boolean).map(renderLine)}
        </div>
      )}
    </div>
  );
}

function SuggestionCard({ result, onLoad }) {
  const { symbol, combined_score, change_pct, intraday, swing } = result;
  const swingSig    = swing.signal;
  const intradaySig = intraday.signal;

  return (
    <div className="suggestion-card">
      <div className="suggestion-header">
        <span className="suggestion-symbol">{symbol}</span>
        <span className={`signal-badge ${swingSig.signal.toLowerCase()}`}>
          {swingSig.signal}
        </span>
      </div>

      {change_pct > 0 && (
        <div className="suggestion-change">
          <span className="label">Today</span>
          <span className="value positive">+{change_pct}%</span>
        </div>
      )}

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
  const [scanning,    setScanning]    = useState(false);
  const [results,     setResults]     = useState(null);
  const [error,       setError]       = useState(null);
  const [phase,       setPhase]       = useState("");
  const [aiReport,    setAiReport]    = useState(null);
  const [aiLoading,   setAiLoading]   = useState(false);

  const fetchAiReport = async (buy, sell) => {
    if (!buy.length && !sell.length) return;
    setAiLoading(true);
    try {
      const res = await api.post("/api/scanner-ai-report", {
        buy_suggestions:  buy,
        sell_suggestions: sell,
      });
      setAiReport(res.data.report);
    } catch {
      // AI report is optional — don't block if it fails
    } finally {
      setAiLoading(false);
    }
  };

  const runScan = async () => {
    setScanning(true);
    setError(null);
    setResults(null);
    setAiReport(null);
    setPhase("Phase 1 — fetching live quotes for all stocks...");

    try {
      const res = await api.post("/api/market-scan", { max_results: 5, max_candidates: 40 });
      setPhase("Phase 2 complete. Generating AI report...");
      setResults(res.data);

      // Kick off AI report in parallel — don't await, let it fill in
      fetchAiReport(res.data.buy_suggestions, res.data.sell_suggestions);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setScanning(false);
      setPhase("");
    }
  };

  const handleLoad = (result) => {
    onLoadInstrument({ instrument_key: result.instrument_key, symbol: result.symbol });
  };

  return (
    <div className="panel scanner-panel">
      {/* Header */}
      <div className="scanner-header">
        <h3>Market Scanner</h3>
        <div className="scanner-header-right">
          {results && !scanning && (
            <span className="scanner-meta">
              {results.universe_size} stocks → {results.candidates} analysed → {results.scanned} valid
            </span>
          )}
          <button className="scan-btn" onClick={runScan} disabled={scanning}>
            {scanning ? "Scanning..." : "Scan NSE Universe"}
          </button>
        </div>
      </div>

      {error && <div className="error-text" style={{ marginTop: "0.5rem" }}>{error}</div>}

      {scanning && (
        <div className="scanner-loading">
          <div className="scanner-phase">{phase || "Phase 2 — deep analysis on top movers..."}</div>
          <div className="scanner-hint">Analysing ~40 stocks in parallel. Takes 30–60 s.</div>
        </div>
      )}

      {!scanning && results && (
        <>
          <MoversBadge movers={results.phase1_movers} />

          {/* AI Report — shown first, prominently */}
          <AIReport report={aiReport} loading={aiLoading} />

          {/* Card grid results */}
          <div className="scanner-results">
            <div className="scanner-section">
              <div className="scanner-section-title buy-title">
                Stocks to Buy ({results.buy_suggestions.length})
              </div>
              {results.buy_suggestions.length === 0 ? (
                <div className="scanner-empty">No strong buy signals among today's movers</div>
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
                Stocks to Avoid ({results.sell_suggestions.length})
              </div>
              {results.sell_suggestions.length === 0 ? (
                <div className="scanner-empty">No strong sell signals among today's movers</div>
              ) : (
                <div className="suggestions-grid">
                  {results.sell_suggestions.map((r) => (
                    <SuggestionCard key={r.symbol} result={r} onLoad={handleLoad} />
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {!scanning && !results && (
        <div className="scanner-placeholder">
          Click <strong>Scan NSE Universe</strong> — scans ~150 NSE stocks, filters today's top
          movers, runs deep ML analysis, then generates an <strong>AI report</strong> telling you
          exactly which stocks to pick and which to avoid today.
        </div>
      )}
    </div>
  );
}
