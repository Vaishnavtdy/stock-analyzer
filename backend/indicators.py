import pandas as pd
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import EMAIndicator, MACD
from ta.volatility import AverageTrueRange, BollingerBands
from ta.volume import OnBalanceVolumeIndicator

CANDLE_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "oi"]
NUMERIC_COLUMNS = ["open", "high", "low", "close", "volume", "oi"]


def candles_to_df(candles):
    """Convert Upstox candle list to a pandas DataFrame sorted ascending by timestamp."""
    df = pd.DataFrame(candles, columns=CANDLE_COLUMNS)

    for col in NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    return df


def df_to_chart_data(df: pd.DataFrame, limit: int = 200):
    """Convert OHLCV DataFrame to the format lightweight-charts expects."""
    recent = df.tail(limit)
    candles = []

    for _, row in recent.iterrows():
        candles.append({
            "time": int(row["timestamp"].timestamp()),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        })

    return candles


def _r(value, digits=2):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    return round(float(value), digits)


def compute_all_indicators(df: pd.DataFrame) -> dict:
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    current_price = close.iloc[-1]

    # RSI 14
    rsi = RSIIndicator(close=close, window=14).rsi()

    # MACD 12, 26, 9
    macd_ind = MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    macd_line = macd_ind.macd()
    macd_signal = macd_ind.macd_signal()
    macd_hist = macd_ind.macd_diff()

    # EMAs
    ema9 = EMAIndicator(close=close, window=9).ema_indicator()
    ema21 = EMAIndicator(close=close, window=21).ema_indicator()
    ema50 = EMAIndicator(close=close, window=50).ema_indicator()

    # Bollinger Bands
    bb = BollingerBands(close=close, window=20, window_dev=2)
    bb_upper = bb.bollinger_hband()
    bb_mid = bb.bollinger_mavg()
    bb_lower = bb.bollinger_lband()

    # VWAP
    typical_price = (high + low + close) / 3
    vwap_series = (typical_price * volume).cumsum() / volume.cumsum()
    vwap = vwap_series.iloc[-1]

    # ATR 14
    atr = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()

    # OBV
    obv = OnBalanceVolumeIndicator(close=close, volume=volume).on_balance_volume()

    # Support / Resistance from last 20 candles
    last_20 = df.tail(20)
    support = last_20["low"].min()
    resistance = last_20["high"].max()

    # Stochastic
    stoch = StochasticOscillator(high=high, low=low, close=close, window=14)
    stoch_k = stoch.stoch()
    stoch_d = stoch.stoch_signal()

    # Volume spike
    avg_volume_20 = volume.tail(20).mean()
    current_volume = volume.iloc[-1]
    volume_spike = bool(current_volume > 1.5 * avg_volume_20) if avg_volume_20 else False

    ema21_last = ema21.iloc[-1]

    return {
        "current_price": _r(current_price),
        "rsi": _r(rsi.iloc[-1]),
        "macd": {
            "line": _r(macd_line.iloc[-1]),
            "signal": _r(macd_signal.iloc[-1]),
            "histogram": _r(macd_hist.iloc[-1]),
        },
        "ema": {
            "ema9": _r(ema9.iloc[-1]),
            "ema21": _r(ema21_last),
            "ema50": _r(ema50.iloc[-1]),
        },
        "bollinger": {
            "upper": _r(bb_upper.iloc[-1]),
            "mid": _r(bb_mid.iloc[-1]),
            "lower": _r(bb_lower.iloc[-1]),
        },
        "vwap": _r(vwap),
        "atr": _r(atr.iloc[-1]),
        "obv": _r(obv.iloc[-1]),
        "support": _r(support),
        "resistance": _r(resistance),
        "stochastic": {
            "k": _r(stoch_k.iloc[-1]),
            "d": _r(stoch_d.iloc[-1]),
        },
        "above_vwap": bool(current_price > vwap),
        "above_ema21": bool(current_price > ema21_last),
        "volume_spike": volume_spike,
    }
