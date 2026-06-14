import os

import joblib
import pandas as pd
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import AverageTrueRange, BollingerBands
from xgboost import XGBClassifier

MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")
os.makedirs(MODELS_DIR, exist_ok=True)

INTRADAY_MODEL_PATH = os.path.join(MODELS_DIR, "intraday_model.pkl")
INTRADAY_FEATURES_PATH = os.path.join(MODELS_DIR, "feature_cols_intraday.pkl")

SWING_MODEL_PATH = os.path.join(MODELS_DIR, "swing_model.pkl")
SWING_FEATURES_PATH = os.path.join(MODELS_DIR, "feature_cols_swing.pkl")


def create_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build the ML feature set from an OHLCV DataFrame."""
    data = df.copy()

    close = data["close"]
    high = data["high"]
    low = data["low"]
    open_ = data["open"]
    volume = data["volume"]

    data["returns"] = close.pct_change()
    data["rsi_14"] = RSIIndicator(close=close, window=14).rsi()

    macd = MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    data["macd_diff"] = macd.macd_diff()

    ema9 = EMAIndicator(close=close, window=9).ema_indicator()
    ema21 = EMAIndicator(close=close, window=21).ema_indicator()
    data["ema9"] = ema9
    data["ema21"] = ema21
    data["ema_cross"] = ema9 - ema21

    bb = BollingerBands(close=close, window=20, window_dev=2)
    data["bb_width"] = bb.bollinger_hband() - bb.bollinger_lband()

    data["atr_14"] = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()

    data["volume_change"] = volume.pct_change()
    data["high_low_pct"] = (high - low) / close
    data["candle_body"] = (close - open_).abs() / close

    typical_price = (high + low + close) / 3
    vwap = (typical_price * volume).cumsum() / volume.cumsum()
    data["price_vs_vwap"] = (close - vwap) / vwap

    data = data.dropna().reset_index(drop=True)
    return data


FEATURE_COLUMNS = [
    "returns",
    "rsi_14",
    "macd_diff",
    "ema9",
    "ema21",
    "ema_cross",
    "bb_width",
    "atr_14",
    "volume_change",
    "high_low_pct",
    "candle_body",
    "price_vs_vwap",
]


def train_intraday_model(df: pd.DataFrame) -> dict:
    """Train the intraday (5-min) direction classifier."""
    data = create_features(df)

    data["target"] = (data["close"].shift(-1) > data["close"]).astype(int)
    data = data.iloc[:-1]  # drop last row with no future target

    X = data[FEATURE_COLUMNS]
    y = data["target"]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

    model = XGBClassifier(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="logloss",
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)

    joblib.dump(model, INTRADAY_MODEL_PATH)
    joblib.dump(FEATURE_COLUMNS, INTRADAY_FEATURES_PATH)

    return {"accuracy": round(float(accuracy), 4), "samples": int(len(data))}


def train_swing_model(df: pd.DataFrame) -> dict:
    """Train the swing (3-day horizon) direction classifier on daily candles."""
    data = create_features(df)

    data["target"] = (data["close"].shift(-3) > data["close"]).astype(int)
    data = data.iloc[:-3]  # drop rows with no future target

    X = data[FEATURE_COLUMNS]
    y = data["target"]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

    model = XGBClassifier(
        n_estimators=150,
        max_depth=4,
        learning_rate=0.05,
        eval_metric="logloss",
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)

    joblib.dump(model, SWING_MODEL_PATH)
    joblib.dump(FEATURE_COLUMNS, SWING_FEATURES_PATH)

    return {"accuracy": round(float(accuracy), 4), "samples": int(len(data))}


def predict_intraday(df: pd.DataFrame) -> dict:
    if not os.path.exists(INTRADAY_MODEL_PATH) or not os.path.exists(INTRADAY_FEATURES_PATH):
        train_intraday_model(df)

    model = joblib.load(INTRADAY_MODEL_PATH)
    feature_cols = joblib.load(INTRADAY_FEATURES_PATH)

    data = create_features(df)
    last_row = data[feature_cols].iloc[[-1]]

    probabilities = model.predict_proba(last_row)[0]
    prob_down, prob_up = float(probabilities[0]), float(probabilities[1])

    direction = "UP" if prob_up >= prob_down else "DOWN"
    confidence = max(prob_up, prob_down)

    return {
        "direction": direction,
        "confidence": round(confidence, 4),
        "prob_up": round(prob_up, 4),
        "prob_down": round(prob_down, 4),
    }


def predict_swing(df: pd.DataFrame) -> dict:
    if not os.path.exists(SWING_MODEL_PATH) or not os.path.exists(SWING_FEATURES_PATH):
        train_swing_model(df)

    model = joblib.load(SWING_MODEL_PATH)
    feature_cols = joblib.load(SWING_FEATURES_PATH)

    data = create_features(df)
    last_row = data[feature_cols].iloc[[-1]]

    probabilities = model.predict_proba(last_row)[0]
    prob_down, prob_up = float(probabilities[0]), float(probabilities[1])

    direction = "UP" if prob_up >= prob_down else "DOWN"
    confidence = max(prob_up, prob_down)

    return {
        "direction": direction,
        "confidence": round(confidence, 4),
        "prob_up": round(prob_up, 4),
        "prob_down": round(prob_down, 4),
        "days": 3,
    }
