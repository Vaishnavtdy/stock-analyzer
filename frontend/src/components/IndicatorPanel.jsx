function IndicatorPanel({ title, indicators }) {
  if (!indicators) {
    return <div className="panel indicator-panel">No indicator data yet</div>;
  }

  return (
    <div className="panel indicator-panel">
      <h3>{title}</h3>
      <div className="indicator-grid">
        <div className="indicator-item">
          <span className="label">Price</span>
          <span className="value">{indicators.current_price}</span>
        </div>
        <div className="indicator-item">
          <span className="label">RSI (14)</span>
          <span className="value">{indicators.rsi}</span>
        </div>
        <div className="indicator-item">
          <span className="label">MACD</span>
          <span className="value">
            {indicators.macd.line} / {indicators.macd.signal} / {indicators.macd.histogram}
          </span>
        </div>
        <div className="indicator-item">
          <span className="label">EMA 9/21/50</span>
          <span className="value">
            {indicators.ema.ema9} / {indicators.ema.ema21} / {indicators.ema.ema50}
          </span>
        </div>
        <div className="indicator-item">
          <span className="label">Bollinger</span>
          <span className="value">
            {indicators.bollinger.upper} / {indicators.bollinger.mid} / {indicators.bollinger.lower}
          </span>
        </div>
        <div className="indicator-item">
          <span className="label">VWAP</span>
          <span className="value">{indicators.vwap}</span>
        </div>
        <div className="indicator-item">
          <span className="label">ATR (14)</span>
          <span className="value">{indicators.atr}</span>
        </div>
        <div className="indicator-item">
          <span className="label">OBV</span>
          <span className="value">{indicators.obv}</span>
        </div>
        <div className="indicator-item">
          <span className="label">Support / Resistance</span>
          <span className="value">
            {indicators.support} / {indicators.resistance}
          </span>
        </div>
        <div className="indicator-item">
          <span className="label">Stochastic %K/%D</span>
          <span className="value">
            {indicators.stochastic.k} / {indicators.stochastic.d}
          </span>
        </div>
      </div>

      <div className="indicator-flags">
        <span className={`flag ${indicators.above_vwap ? "on" : "off"}`}>Above VWAP</span>
        <span className={`flag ${indicators.above_ema21 ? "on" : "off"}`}>Above EMA21</span>
        <span className={`flag ${indicators.volume_spike ? "on" : "off"}`}>Volume Spike</span>
      </div>
    </div>
  );
}

export default IndicatorPanel;
