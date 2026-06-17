"""
ML prediction engine — dual-model architecture
  Intraday : Enhanced XGBoost (35 features)
  Swing    : BiLSTM (60 %) + XGBoost (40 %) weighted ensemble
"""

import os
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.metrics import accuracy_score
from sklearn.preprocessing import StandardScaler
from ta.momentum import RSIIndicator, StochasticOscillator, WilliamsRIndicator
from ta.trend import ADXIndicator, CCIIndicator, EMAIndicator, MACD
from ta.volatility import AverageTrueRange, BollingerBands
from ta.volume import MFIIndicator, OnBalanceVolumeIndicator
from xgboost import XGBClassifier

warnings.filterwarnings("ignore")

# ── Paths ─────────────────────────────────────────────────────────────────────

MODELS_DIR = Path(os.path.dirname(__file__)) / "models"
MODELS_DIR.mkdir(exist_ok=True)

INTRADAY_MODEL_PATH    = MODELS_DIR / "intraday_model.pkl"
INTRADAY_FEATURES_PATH = MODELS_DIR / "feature_cols_intraday.pkl"
SWING_MODEL_PATH       = MODELS_DIR / "swing_model.pkl"
SWING_FEATURES_PATH    = MODELS_DIR / "feature_cols_swing.pkl"
BILSTM_WEIGHTS_PATH    = MODELS_DIR / "swing_bilstm.pt"
BILSTM_SCALER_PATH     = MODELS_DIR / "swing_bilstm_scaler.pkl"
BILSTM_INPUT_SIZE_PATH = MODELS_DIR / "swing_bilstm_input_size.pkl"

SEQ_LEN = 30  # candles fed into BiLSTM as one sequence


def _get_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    try:
        if torch.backends.mps.is_available():
            return torch.device("mps")
    except AttributeError:
        pass
    return torch.device("cpu")


DEVICE = _get_device()


# ── BiLSTM Architecture ───────────────────────────────────────────────────────

class BiLSTMClassifier(nn.Module):
    """Bidirectional LSTM binary classifier for directional prediction."""

    def __init__(self, input_size: int, hidden_size: int = 128, num_layers: int = 2, dropout: float = 0.4):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size,
            hidden_size,
            num_layers=num_layers,
            batch_first=True,
            bidirectional=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.classifier = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(hidden_size * 2, 64),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(64, 1),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        return self.classifier(out[:, -1, :])  # last timestep → P(UP)


# ── Feature Engineering ───────────────────────────────────────────────────────

def create_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build 35 technical features from an OHLCV DataFrame."""
    data = df.copy()
    close  = data["close"]
    high   = data["high"]
    low    = data["low"]
    open_  = data["open"]
    volume = data["volume"]

    # ── Returns ───────────────────────────────────────────────────────────────
    data["returns"]   = close.pct_change()
    data["return_5"]  = close.pct_change(5)
    data["return_10"] = close.pct_change(10)
    data["return_20"] = close.pct_change(20)

    # ── RSI ───────────────────────────────────────────────────────────────────
    data["rsi_14"] = RSIIndicator(close=close, window=14).rsi()

    # ── MACD ─────────────────────────────────────────────────────────────────
    macd_ind = MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    data["macd_diff"]        = macd_ind.macd_diff()
    data["macd_line"]        = macd_ind.macd()
    data["macd_signal_line"] = macd_ind.macd_signal()

    # ── EMAs ──────────────────────────────────────────────────────────────────
    ema9  = EMAIndicator(close=close, window=9).ema_indicator()
    ema21 = EMAIndicator(close=close, window=21).ema_indicator()
    ema50 = EMAIndicator(close=close, window=50).ema_indicator()
    data["ema9"]          = ema9
    data["ema21"]         = ema21
    data["ema50"]         = ema50
    data["ema_cross"]     = ema9 - ema21                          # positive = bullish
    data["price_vs_ema21"] = (close - ema21) / (ema21 + 1e-9)
    data["price_vs_ema50"] = (close - ema50) / (ema50 + 1e-9)

    # ── Bollinger Bands ───────────────────────────────────────────────────────
    bb = BollingerBands(close=close, window=20, window_dev=2)
    bb_upper = bb.bollinger_hband()
    bb_lower = bb.bollinger_lband()
    bb_mid   = bb.bollinger_mavg()
    data["bb_width"]    = (bb_upper - bb_lower) / (bb_mid + 1e-9)
    data["bb_position"] = (close - bb_lower) / (bb_upper - bb_lower + 1e-9)

    # ── ATR ───────────────────────────────────────────────────────────────────
    data["atr_14"] = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()

    # ── ADX (trend strength + directional indicators) ─────────────────────────
    adx_ind = ADXIndicator(high=high, low=low, close=close, window=14)
    data["adx"]     = adx_ind.adx()
    data["adx_pos"] = adx_ind.adx_pos()   # +DI
    data["adx_neg"] = adx_ind.adx_neg()   # -DI

    # ── CCI ───────────────────────────────────────────────────────────────────
    data["cci"] = CCIIndicator(high=high, low=low, close=close, window=20).cci()

    # ── Williams %R ───────────────────────────────────────────────────────────
    data["williams_r"] = WilliamsRIndicator(high=high, low=low, close=close, lbp=14).williams_r()

    # ── MFI (Money Flow Index) ────────────────────────────────────────────────
    data["mfi"] = MFIIndicator(high=high, low=low, close=close, volume=volume, window=14).money_flow_index()

    # ── Stochastic ────────────────────────────────────────────────────────────
    stoch = StochasticOscillator(high=high, low=low, close=close, window=14)
    data["stoch_k"] = stoch.stoch()
    data["stoch_d"] = stoch.stoch_signal()

    # ── VWAP ──────────────────────────────────────────────────────────────────
    typical = (high + low + close) / 3
    vwap = (typical * volume).cumsum() / (volume.cumsum() + 1e-9)
    data["price_vs_vwap"] = (close - vwap) / (vwap + 1e-9)

    # ── Volume ────────────────────────────────────────────────────────────────
    vol_ma20 = volume.rolling(20).mean()
    vol_ma50 = volume.rolling(50).mean()
    data["volume_change"]   = volume.pct_change()
    data["volume_ratio_20"] = volume / (vol_ma20 + 1)
    data["volume_ratio_50"] = volume / (vol_ma50 + 1)

    # ── OBV momentum (5-period) ───────────────────────────────────────────────
    obv = OnBalanceVolumeIndicator(close=close, volume=volume).on_balance_volume()
    data["obv_change"] = obv.pct_change(5)

    # ── Candle anatomy ────────────────────────────────────────────────────────
    candle_range = (high - low) + 1e-9
    data["high_low_pct"]  = (high - low) / (close + 1e-9)
    data["candle_body"]   = (close - open_).abs() / candle_range
    data["upper_shadow"]  = (high - close.combine(open_, max)) / candle_range
    data["lower_shadow"]  = (close.combine(open_, min) - low) / candle_range
    data["is_doji"]       = ((close - open_).abs() / candle_range < 0.1).astype(float)
    data["is_bullish"]    = (close > open_).astype(float)

    data = data.dropna().reset_index(drop=True)
    return data


FEATURE_COLUMNS = [
    # returns
    "returns", "return_5", "return_10", "return_20",
    # momentum
    "rsi_14", "macd_diff", "macd_line", "macd_signal_line",
    "stoch_k", "stoch_d", "williams_r", "mfi", "cci",
    # trend
    "ema9", "ema21", "ema50", "ema_cross", "price_vs_ema21", "price_vs_ema50",
    "adx", "adx_pos", "adx_neg",
    # volatility
    "bb_width", "bb_position", "atr_14",
    # volume / price-volume
    "price_vs_vwap", "volume_change", "volume_ratio_20", "volume_ratio_50", "obv_change",
    # candle structure
    "high_low_pct", "candle_body", "upper_shadow", "lower_shadow", "is_doji", "is_bullish",
]


def _needs_retrain(feature_path: Path) -> bool:
    """True when the saved feature list no longer matches FEATURE_COLUMNS."""
    if not feature_path.exists():
        return True
    try:
        return set(joblib.load(feature_path)) != set(FEATURE_COLUMNS)
    except Exception:
        return True


# ── XGBoost helper ────────────────────────────────────────────────────────────

def _train_xgb(X_train: np.ndarray, y_train: np.ndarray,
                n_estimators: int = 300, max_depth: int = 5,
                lr: float = 0.04) -> XGBClassifier:
    model = XGBClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=lr,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=3,
        gamma=0.1,
        reg_alpha=0.05,
        reg_lambda=1.0,
        eval_metric="logloss",
        random_state=42,
    )
    model.fit(X_train, y_train)
    return model


# ── BiLSTM training helpers ───────────────────────────────────────────────────

def _build_sequences(X: np.ndarray, y: np.ndarray, seq_len: int):
    """Slide a window of seq_len to produce (N, seq_len, features) tensors."""
    xs, ys = [], []
    for i in range(seq_len, len(X)):
        xs.append(X[i - seq_len : i])
        ys.append(y[i])
    return np.array(xs, dtype=np.float32), np.array(ys, dtype=np.float32)


def _augment(X_seq: np.ndarray, y: np.ndarray,
             noise_std: float = 0.01, copies: int = 3):
    """Expand a small dataset with Gaussian-noise copies (no label change)."""
    rng = np.random.default_rng(42)
    Xs, ys = [X_seq], [y]
    for _ in range(copies):
        noise = rng.normal(0, noise_std, X_seq.shape).astype(np.float32)
        Xs.append(X_seq + noise)
        ys.append(y)
    return np.concatenate(Xs), np.concatenate(ys)


def _train_bilstm(
    X_tr: np.ndarray, y_tr: np.ndarray,
    X_vl: np.ndarray, y_vl: np.ndarray,
    input_size: int,
) -> BiLSTMClassifier:
    # 4× training data via noise augmentation
    X_tr, y_tr = _augment(X_tr, y_tr, noise_std=0.01, copies=3)

    model     = BiLSTMClassifier(input_size=input_size).to(DEVICE)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, patience=5, factor=0.5
    )
    criterion = nn.BCELoss()

    Xt = torch.tensor(X_tr).to(DEVICE)
    yt = torch.tensor(y_tr).unsqueeze(1).to(DEVICE)
    Xv = torch.tensor(X_vl).to(DEVICE)
    yv = torch.tensor(y_vl).unsqueeze(1).to(DEVICE)

    best_val_loss = float("inf")
    best_state    = None
    no_improve    = 0
    batch_size    = min(32, len(Xt))

    for _ in range(150):
        model.train()
        perm = torch.randperm(len(Xt), device=DEVICE)
        for i in range(0, len(Xt), batch_size):
            idx = perm[i : i + batch_size]
            optimizer.zero_grad()
            loss = criterion(model(Xt[idx]), yt[idx])
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

        model.eval()
        with torch.no_grad():
            val_loss = criterion(model(Xv), yv).item()
        scheduler.step(val_loss)

        if val_loss < best_val_loss - 1e-4:
            best_val_loss = val_loss
            best_state    = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            no_improve    = 0
        else:
            no_improve += 1
            if no_improve >= 20:
                break

    model.load_state_dict(best_state)
    return model


# ── Public training API ───────────────────────────────────────────────────────

def train_intraday_model(df: pd.DataFrame) -> dict:
    """Train enhanced XGBoost on 5-min candles for next-bar direction."""
    data = create_features(df)
    data["target"] = (data["close"].shift(-1) > data["close"]).astype(int)
    data = data.iloc[:-1].dropna()

    X = data[FEATURE_COLUMNS].values.astype(np.float32)
    y = data["target"].values
    split = int(len(X) * 0.8)

    model    = _train_xgb(X[:split], y[:split], n_estimators=300, max_depth=5, lr=0.04)
    accuracy = float(accuracy_score(y[split:], model.predict(X[split:])))

    joblib.dump(model, INTRADAY_MODEL_PATH)
    joblib.dump(FEATURE_COLUMNS, INTRADAY_FEATURES_PATH)

    return {
        "accuracy": round(accuracy, 4),
        "samples": len(data),
        "features": len(FEATURE_COLUMNS),
        "model": "xgboost",
    }


def train_swing_model(df: pd.DataFrame) -> dict:
    """Train XGBoost + BiLSTM ensemble on daily candles for 3-day direction."""
    data = create_features(df)
    data["target"] = (data["close"].shift(-3) > data["close"]).astype(int)
    data = data.iloc[:-3].dropna()

    X = data[FEATURE_COLUMNS].values.astype(np.float32)
    y = data["target"].values
    split = int(len(X) * 0.8)

    # ── XGBoost ───────────────────────────────────────────────────────────────
    xgb     = _train_xgb(X[:split], y[:split], n_estimators=200, max_depth=4, lr=0.05)
    xgb_acc = float(accuracy_score(y[split:], xgb.predict(X[split:])))

    joblib.dump(xgb, SWING_MODEL_PATH)
    joblib.dump(FEATURE_COLUMNS, SWING_FEATURES_PATH)

    # ── BiLSTM ────────────────────────────────────────────────────────────────
    scaler   = StandardScaler()
    X_scaled = scaler.fit_transform(X).astype(np.float32)
    X_seq, y_seq = _build_sequences(X_scaled, y, SEQ_LEN)

    bilstm_acc = None
    if len(X_seq) >= 20:
        split_seq = int(len(X_seq) * 0.8)
        bilstm = _train_bilstm(
            X_seq[:split_seq], y_seq[:split_seq],
            X_seq[split_seq:], y_seq[split_seq:],
            input_size=len(FEATURE_COLUMNS),
        )
        bilstm.eval()
        with torch.no_grad():
            raw = bilstm(torch.tensor(X_seq[split_seq:]).to(DEVICE)).cpu().numpy().flatten()
        bilstm_acc = float(accuracy_score(y_seq[split_seq:], (raw > 0.5).astype(int)))

        torch.save(bilstm.state_dict(), BILSTM_WEIGHTS_PATH)
        joblib.dump(scaler, BILSTM_SCALER_PATH)
        joblib.dump(len(FEATURE_COLUMNS), BILSTM_INPUT_SIZE_PATH)

    return {
        "xgb_accuracy": round(xgb_acc, 4),
        "bilstm_accuracy": round(bilstm_acc, 4) if bilstm_acc is not None else None,
        "samples": len(data),
        "features": len(FEATURE_COLUMNS),
        "model": "ensemble" if bilstm_acc is not None else "xgboost",
    }


# ── Prediction helpers ────────────────────────────────────────────────────────

def _load_bilstm():
    input_size = joblib.load(BILSTM_INPUT_SIZE_PATH)
    m = BiLSTMClassifier(input_size=input_size).to(DEVICE)
    m.load_state_dict(torch.load(BILSTM_WEIGHTS_PATH, map_location=DEVICE, weights_only=True))
    m.eval()
    scaler = joblib.load(BILSTM_SCALER_PATH)
    return m, scaler


def _confidence_label(prob_up: float) -> str:
    margin = abs(prob_up - 0.5)
    if margin > 0.20:
        return "high"
    if margin > 0.10:
        return "medium"
    return "low"


# ── Public prediction API ─────────────────────────────────────────────────────

def get_features_snapshot(df: pd.DataFrame) -> dict:
    """Return the last row's feature values as a plain dict for storage."""
    data = create_features(df)
    if data.empty:
        return {}
    last = data[FEATURE_COLUMNS].iloc[-1]
    return {col: (float(val) if pd.notna(val) else None) for col, val in last.items()}


def retrain_with_feedback(feedback_samples: list, base_df: pd.DataFrame = None) -> dict:
    """
    Fine-tune the XGBoost models using real paper trade outcomes.

    feedback_samples : list of dicts with keys 'features' (dict), 'outcome' (0|1), 'trade_type'
    base_df          : optional candle DataFrame to blend with feedback data
                       (keeps historical knowledge while absorbing new signal)

    BiLSTM is excluded — it requires 30-candle sequences; single snapshots can't train it.
    Only XGBoost is fine-tuned here.
    """
    results = {}

    for trade_type, model_path, feat_path, n_est, depth in [
        ("INTRADAY", INTRADAY_MODEL_PATH, INTRADAY_FEATURES_PATH, 200, 5),
        ("SWING",    SWING_MODEL_PATH,    SWING_FEATURES_PATH,    150, 4),
    ]:
        samples = [s for s in feedback_samples
                   if s["trade_type"] == trade_type and s.get("outcome") is not None]

        if not samples:
            results[trade_type.lower()] = {"status": "skipped", "reason": "no feedback samples"}
            continue

        # Build feedback feature matrix
        X_fb = np.array(
            [[float(s["features"].get(c) or 0) for c in FEATURE_COLUMNS] for s in samples],
            dtype=np.float32,
        )
        y_fb = np.array([int(s["outcome"]) for s in samples])

        # Blend with historical candle data if provided (3× weight on feedback)
        if base_df is not None and model_path.exists():
            hist = create_features(base_df)
            if trade_type == "INTRADAY":
                hist["target"] = (hist["close"].shift(-1) > hist["close"]).astype(int)
                hist = hist.iloc[:-1].dropna()
            else:
                hist["target"] = (hist["close"].shift(-3) > hist["close"]).astype(int)
                hist = hist.iloc[:-3].dropna()

            for col in FEATURE_COLUMNS:
                if col not in hist.columns:
                    hist[col] = 0.0

            X_hist = hist[FEATURE_COLUMNS].values.astype(np.float32)
            y_hist = hist["target"].values
            # Repeat feedback 3× so real outcomes dominate
            X_train = np.vstack([X_hist, X_fb, X_fb, X_fb])
            y_train = np.concatenate([y_hist, y_fb, y_fb, y_fb])
        else:
            X_train = np.vstack([X_fb, X_fb, X_fb])
            y_train = np.concatenate([y_fb, y_fb, y_fb])

        model = _train_xgb(X_train, y_train, n_estimators=n_est, max_depth=depth, lr=0.03)
        joblib.dump(model, model_path)
        joblib.dump(FEATURE_COLUMNS, feat_path)

        fb_acc = float(accuracy_score(y_fb, model.predict(X_fb)))
        results[trade_type.lower()] = {
            "status": "retrained",
            "feedback_samples": len(samples),
            "feedback_accuracy": round(fb_acc, 4),
        }

    return results


def predict_intraday(df: pd.DataFrame) -> dict:
    if not INTRADAY_MODEL_PATH.exists() or _needs_retrain(INTRADAY_FEATURES_PATH):
        train_intraday_model(df)

    model     = joblib.load(INTRADAY_MODEL_PATH)
    feat_cols = joblib.load(INTRADAY_FEATURES_PATH)

    data = create_features(df)
    if data.empty:
        return {"direction": "NEUTRAL", "confidence": "low", "prob_up": 0.5, "prob_down": 0.5}

    for col in feat_cols:
        if col not in data.columns:
            data[col] = 0.0

    X        = data[feat_cols].iloc[[-1]].values.astype(np.float32)
    probs    = model.predict_proba(X)[0]
    prob_up  = float(probs[1])
    direction = "UP" if prob_up >= 0.5 else "DOWN"

    return {
        "direction":  direction,
        "confidence": _confidence_label(prob_up),
        "prob_up":    round(prob_up, 4),
        "prob_down":  round(1 - prob_up, 4),
        "model":      "xgboost",
    }


def predict_swing(df: pd.DataFrame) -> dict:
    if not SWING_MODEL_PATH.exists() or _needs_retrain(SWING_FEATURES_PATH):
        train_swing_model(df)

    xgb       = joblib.load(SWING_MODEL_PATH)
    feat_cols = joblib.load(SWING_FEATURES_PATH)

    data = create_features(df)
    if data.empty:
        return {"direction": "NEUTRAL", "confidence": "low", "prob_up": 0.5, "prob_down": 0.5}

    for col in feat_cols:
        if col not in data.columns:
            data[col] = 0.0

    X_all = data[feat_cols].values.astype(np.float32)

    # XGBoost probability on the last row
    xgb_prob_up = float(xgb.predict_proba(X_all[[-1]])[0][1])

    # BiLSTM probability on the last SEQ_LEN rows
    bilstm_prob_up = None
    bilstm_files_exist = (
        BILSTM_WEIGHTS_PATH.exists()
        and BILSTM_SCALER_PATH.exists()
        and BILSTM_INPUT_SIZE_PATH.exists()
    )
    if bilstm_files_exist:
        try:
            bilstm, scaler = _load_bilstm()
            X_scaled = scaler.transform(X_all).astype(np.float32)
            if len(X_scaled) >= SEQ_LEN:
                seq = torch.tensor(X_scaled[-SEQ_LEN:]).unsqueeze(0).to(DEVICE)
                with torch.no_grad():
                    bilstm_prob_up = float(bilstm(seq).cpu().item())
        except Exception:
            bilstm_prob_up = None

    # Weighted ensemble: 60 % BiLSTM + 40 % XGBoost
    if bilstm_prob_up is not None:
        prob_up    = 0.4 * xgb_prob_up + 0.6 * bilstm_prob_up
        model_used = "ensemble"
    else:
        prob_up    = xgb_prob_up
        model_used = "xgboost"

    direction = "UP" if prob_up >= 0.5 else "DOWN"

    return {
        "direction":      direction,
        "confidence":     _confidence_label(prob_up),
        "prob_up":        round(prob_up, 4),
        "prob_down":      round(1 - prob_up, 4),
        "model":          model_used,
        "xgb_prob_up":    round(xgb_prob_up, 4),
        "bilstm_prob_up": round(bilstm_prob_up, 4) if bilstm_prob_up is not None else None,
        "days":           3,
    }
