def _score_conditions(indicators: dict, ml_prediction: dict):
    """Shared scoring logic for intraday and swing signals."""
    score = 0
    reasoning = []

    rsi = indicators.get("rsi")
    if rsi is not None:
        if rsi < 40:
            score += 1
            reasoning.append(f"RSI {rsi} is below 40 (oversold) — bullish")
        elif rsi > 70:
            reasoning.append(f"RSI {rsi} is above 70 (overbought) — bearish")
        else:
            reasoning.append(f"RSI {rsi} is neutral")

    macd_hist = indicators.get("macd", {}).get("histogram")
    if macd_hist is not None:
        if macd_hist > 0:
            score += 1
            reasoning.append(f"MACD histogram {macd_hist} is positive — bullish")
        else:
            reasoning.append(f"MACD histogram {macd_hist} is negative — bearish")

    if indicators.get("above_vwap"):
        score += 1
        reasoning.append("Price is above VWAP — bullish")
    else:
        reasoning.append("Price is below VWAP — bearish")

    if indicators.get("above_ema21"):
        score += 1
        reasoning.append("Price is above EMA21 — bullish")
    else:
        reasoning.append("Price is below EMA21 — bearish")

    ema9 = indicators.get("ema", {}).get("ema9")
    ema21 = indicators.get("ema", {}).get("ema21")
    if ema9 is not None and ema21 is not None:
        if ema9 > ema21:
            score += 1
            reasoning.append(f"EMA9 ({ema9}) is above EMA21 ({ema21}) — bullish")
        else:
            reasoning.append(f"EMA9 ({ema9}) is below EMA21 ({ema21}) — bearish")

    ml_direction = ml_prediction.get("direction")
    ml_confidence = ml_prediction.get("confidence")
    if ml_direction == "UP":
        score += 2
        reasoning.append(f"ML model predicts UP with {ml_confidence} confidence — bullish (weight x2)")
    else:
        reasoning.append(f"ML model predicts DOWN with {ml_confidence} confidence — bearish")

    return score, reasoning


def _classify(score: int) -> str:
    if score >= 4:
        return "BUY"
    if score <= 1:
        return "SELL"
    return "NEUTRAL"


def generate_intraday_signal(indicators: dict, ml_prediction: dict) -> dict:
    score, reasoning = _score_conditions(indicators, ml_prediction)
    signal = _classify(score)

    entry = indicators.get("current_price")
    atr = indicators.get("atr") or 0

    target = None
    stop_loss = None
    risk_reward = None

    if signal == "BUY":
        target = round(entry + (atr * 1.5), 2)
        stop_loss = round(entry - atr, 2)
    elif signal == "SELL":
        target = round(entry - (atr * 1.5), 2)
        stop_loss = round(entry + atr, 2)

    if target is not None and stop_loss is not None and (entry - stop_loss) != 0:
        risk_reward = round(abs(target - entry) / abs(stop_loss - entry), 2)

    return {
        "signal": signal,
        "entry": entry,
        "target": target,
        "stop_loss": stop_loss,
        "risk_reward": risk_reward,
        "score": score,
        "ml_confidence": ml_prediction.get("confidence"),
        "reasoning": reasoning,
    }


def generate_swing_signal(indicators: dict, ml_prediction: dict) -> dict:
    score, reasoning = _score_conditions(indicators, ml_prediction)
    signal = _classify(score)

    entry = indicators.get("current_price")
    atr = indicators.get("atr") or 0

    target = None
    stop_loss = None
    risk_reward = None

    if signal == "BUY":
        target = round(entry + (atr * 3), 2)
        stop_loss = round(entry - (atr * 1.5), 2)
    elif signal == "SELL":
        target = round(entry - (atr * 3), 2)
        stop_loss = round(entry + (atr * 1.5), 2)

    if target is not None and stop_loss is not None and (entry - stop_loss) != 0:
        risk_reward = round(abs(target - entry) / abs(stop_loss - entry), 2)

    return {
        "signal": signal,
        "entry": entry,
        "target": target,
        "stop_loss": stop_loss,
        "risk_reward": risk_reward,
        "score": score,
        "ml_confidence": ml_prediction.get("confidence"),
        "reasoning": reasoning,
        "horizon": "3-5 days",
    }
