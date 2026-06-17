import { useState } from "react";
import AIAnalyst from "./components/AIAnalyst";
import CandleChart from "./components/CandleChart";
import Header from "./components/Header";
import IndicatorPanel from "./components/IndicatorPanel";
import LiveTicker from "./components/LiveTicker";
import MarketScanner from "./components/MarketScanner";
import PaperTrade from "./components/PaperTrade";
import SignalPanel from "./components/SignalPanel";
import SwingPanel from "./components/SwingPanel";
import api from "./api";

function App() {
  const [instrument, setInstrument] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSelectInstrument = (selected) => {
    setInstrument(selected);
    setAnalysis(null);
    setError(null);
  };

  const runAnalysis = async (inst) => {
    const target = inst || instrument;
    if (!target) return;

    setLoading(true);
    setError(null);

    try {
      const res = await api.post("/api/analyze", {
        instrument_key: target.instrument_key,
        symbol: target.symbol,
      });
      setAnalysis(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleLoadFromScanner = (inst) => {
    setInstrument(inst);
    setAnalysis(null);
    setError(null);
    runAnalysis(inst);
  };

  return (
    <div className="app">
      <Header selectedSymbol={instrument?.symbol} onSelectInstrument={handleSelectInstrument} />

      <div className="toolbar">
        <button className="analyze-btn" onClick={() => runAnalysis()} disabled={!instrument || loading}>
          {loading ? "Analyzing..." : "Run Analysis"}
        </button>
        {error && <span className="error-text">{error}</span>}
      </div>

      <div className="dashboard">
        <div className="dashboard-col main-col">
          <LiveTicker instrumentKey={instrument?.instrument_key} symbol={instrument?.symbol} />
          <CandleChart title="Intraday (5-min)" candles={analysis?.intraday?.candles} />
          <CandleChart title="Swing (Daily)" candles={analysis?.swing?.candles} />
          <AIAnalyst analysis={analysis} />
          <PaperTrade />
        </div>

        <div className="dashboard-col side-col">
          <SignalPanel
            symbol={instrument?.symbol}
            signal={analysis?.intraday?.signal}
            prediction={analysis?.intraday?.prediction}
            featuresSnapshot={analysis?.intraday?.features_snapshot}
            instrumentKey={instrument?.instrument_key}
          />
          <IndicatorPanel title="Intraday Indicators" indicators={analysis?.intraday?.indicators} />
          <SwingPanel
            symbol={instrument?.symbol}
            signal={analysis?.swing?.signal}
            prediction={analysis?.swing?.prediction}
            featuresSnapshot={analysis?.swing?.features_snapshot}
            instrumentKey={instrument?.instrument_key}
          />
          <IndicatorPanel title="Swing Indicators" indicators={analysis?.swing?.indicators} />
        </div>
      </div>

      <div className="scanner-wrapper">
        <MarketScanner onLoadInstrument={handleLoadFromScanner} />
      </div>
    </div>
  );
}

export default App;
