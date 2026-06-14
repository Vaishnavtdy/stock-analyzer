import { useEffect, useState } from "react";
import api from "../api";
import useWebSocket from "../hooks/useWebSocket";

function extractFeed(tick, instrumentKey) {
  if (!tick) return null;
  const feeds = tick.feeds || tick.data;
  if (!feeds) return null;
  return feeds[instrumentKey] || null;
}

function LiveTicker({ instrumentKey, symbol }) {
  const [quote, setQuote] = useState(null);
  const { tick, connected } = useWebSocket(instrumentKey ? [instrumentKey] : []);

  useEffect(() => {
    if (!instrumentKey) return;

    const fetchQuote = async () => {
      try {
        const res = await api.get("/api/quote", { params: { keys: instrumentKey } });
        const data = res.data.data || {};
        const first = Object.values(data)[0];
        setQuote(first || null);
      } catch {
        setQuote(null);
      }
    };

    fetchQuote();
  }, [instrumentKey]);

  if (!instrumentKey) {
    return <div className="panel live-ticker">Select a symbol to see live price</div>;
  }

  const feed = extractFeed(tick, instrumentKey);
  const ltpc = feed?.ltpc || feed?.fullFeed?.marketFF?.ltpc;

  const ltp = ltpc?.ltp ?? quote?.last_price;
  const close = ltpc?.cp ?? quote?.ohlc?.close;
  const change = ltp != null && close ? ltp - close : null;
  const changePct = change != null && close ? (change / close) * 100 : null;

  return (
    <div className="panel live-ticker">
      <div className="ticker-symbol">
        {symbol}
        <span className={`ws-dot ${connected ? "live" : "offline"}`} title={connected ? "Live" : "Offline"} />
      </div>
      <div className="ticker-price">{ltp != null ? `₹${Number(ltp).toFixed(2)}` : "--"}</div>
      {change != null && (
        <div className={`ticker-change ${change >= 0 ? "positive" : "negative"}`}>
          {change >= 0 ? "+" : ""}
          {change.toFixed(2)} ({changePct.toFixed(2)}%)
        </div>
      )}
      {quote?.ohlc && (
        <div className="ticker-ohlc">
          <span>O: {quote.ohlc.open}</span>
          <span>H: {quote.ohlc.high}</span>
          <span>L: {quote.ohlc.low}</span>
          <span>C: {quote.ohlc.close}</span>
        </div>
      )}
    </div>
  );
}

export default LiveTicker;
