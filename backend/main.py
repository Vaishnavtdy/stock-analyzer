import asyncio
import os
from datetime import datetime, timedelta
from typing import Any, Dict

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import paper_trade
import upstox
from auth import router as auth_router
from indicators import candles_to_df, compute_all_indicators, df_to_chart_data
from ml_model import (get_features_snapshot, predict_intraday, predict_swing,
                       retrain_with_feedback, train_intraday_model, train_swing_model)
from signals import generate_intraday_signal, generate_swing_signal

app = FastAPI(title="MarketPulse Pro API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)


@app.exception_handler(httpx.HTTPStatusError)
async def upstox_error_handler(request, exc: httpx.HTTPStatusError):
    return JSONResponse(status_code=exc.response.status_code, content={"detail": exc.response.text})


def _date_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    instrument_key: str
    symbol: str


class TrainRequest(BaseModel):
    instrument_key: str
    interval: str


class PaperTradeRequest(BaseModel):
    symbol: str
    signal: str
    entry: float
    target: float
    stop_loss: float
    type: str
    instrument_key: str = None
    features_snapshot: dict = None


class ExitTradeRequest(BaseModel):
    exit_price: float


class AIAnalystRequest(BaseModel):
    analysis: Dict[str, Any]


class MarketScanRequest(BaseModel):
    instruments: list = None   # optional custom list; falls back to NSE_UNIVERSE
    max_results: int = 5       # top N BUY + top N SELL to return
    max_candidates: int = 40   # how many stocks to deep-analyse after Phase-1 filter


# ~150-stock NSE universe: Nifty 100 + popular midcaps (instrument_key = NSE_EQ|ISIN)
NSE_UNIVERSE = [
    # ── Nifty 50 ──────────────────────────────────────────────────────────────
    {"instrument_key": "NSE_EQ|INE002A01018", "symbol": "RELIANCE"},
    {"instrument_key": "NSE_EQ|INE467B01029", "symbol": "TCS"},
    {"instrument_key": "NSE_EQ|INE040A01034", "symbol": "HDFCBANK"},
    {"instrument_key": "NSE_EQ|INE009A01021", "symbol": "INFY"},
    {"instrument_key": "NSE_EQ|INE090A01021", "symbol": "ICICIBANK"},
    {"instrument_key": "NSE_EQ|INE397D01024", "symbol": "BHARTIARTL"},
    {"instrument_key": "NSE_EQ|INE062A01020", "symbol": "SBIN"},
    {"instrument_key": "NSE_EQ|INE296A01024", "symbol": "BAJFINANCE"},
    {"instrument_key": "NSE_EQ|INE075A01022", "symbol": "WIPRO"},
    {"instrument_key": "NSE_EQ|INE021A01026", "symbol": "ASIANPAINT"},
    {"instrument_key": "NSE_EQ|INE860A01027", "symbol": "HCLTECH"},
    {"instrument_key": "NSE_EQ|INE101A01026", "symbol": "M&M"},
    {"instrument_key": "NSE_EQ|INE585B01010", "symbol": "MARUTI"},
    {"instrument_key": "NSE_EQ|INE280A01028", "symbol": "TITAN"},
    {"instrument_key": "NSE_EQ|INE044A01036", "symbol": "SUNPHARMA"},
    {"instrument_key": "NSE_EQ|INE237A01028", "symbol": "KOTAKBANK"},
    {"instrument_key": "NSE_EQ|INE238A01034", "symbol": "AXISBANK"},
    {"instrument_key": "NSE_EQ|INE669C01036", "symbol": "TECHM"},
    {"instrument_key": "NSE_EQ|INE018A01030", "symbol": "LT"},
    {"instrument_key": "NSE_EQ|INE038A01020", "symbol": "HINDALCO"},
    {"instrument_key": "NSE_EQ|INE155A01022", "symbol": "TATAMOTORS"},
    {"instrument_key": "NSE_EQ|INE081A01020", "symbol": "TATASTEEL"},
    {"instrument_key": "NSE_EQ|INE733E01010", "symbol": "NTPC"},
    {"instrument_key": "NSE_EQ|INE213A01029", "symbol": "ONGC"},
    {"instrument_key": "NSE_EQ|INE522F01014", "symbol": "COALINDIA"},
    {"instrument_key": "NSE_EQ|INE752E01010", "symbol": "POWERGRID"},
    {"instrument_key": "NSE_EQ|INE095A01012", "symbol": "INDUSINDBK"},
    {"instrument_key": "NSE_EQ|INE158A01026", "symbol": "HEROMOTOCO"},
    {"instrument_key": "NSE_EQ|INE059A01026", "symbol": "CIPLA"},
    {"instrument_key": "NSE_EQ|INE089A01031", "symbol": "DRREDDY"},
    {"instrument_key": "NSE_EQ|INE361B01024", "symbol": "DIVISLAB"},
    {"instrument_key": "NSE_EQ|INE239A01016", "symbol": "NESTLEIND"},
    {"instrument_key": "NSE_EQ|INE481G01011", "symbol": "ULTRACEMCO"},
    {"instrument_key": "NSE_EQ|INE047A01021", "symbol": "GRASIM"},
    {"instrument_key": "NSE_EQ|INE917I01010", "symbol": "BAJAJ-AUTO"},
    {"instrument_key": "NSE_EQ|INE795G01014", "symbol": "HDFCLIFE"},
    {"instrument_key": "NSE_EQ|INE423A01024", "symbol": "ADANIENT"},
    {"instrument_key": "NSE_EQ|INE742F01042", "symbol": "ADANIPORTS"},
    {"instrument_key": "NSE_EQ|INE066A01021", "symbol": "EICHERMOT"},
    {"instrument_key": "NSE_EQ|INE216A01030", "symbol": "BRITANNIA"},
    # ── Nifty Next 50 ─────────────────────────────────────────────────────────
    {"instrument_key": "NSE_EQ|INE918I01026", "symbol": "BAJAJFINSV"},
    {"instrument_key": "NSE_EQ|INE003A01024", "symbol": "SIEMENS"},
    {"instrument_key": "NSE_EQ|INE176B01034", "symbol": "HAVELLS"},
    {"instrument_key": "NSE_EQ|INE016A01026", "symbol": "DABUR"},
    {"instrument_key": "NSE_EQ|INE102D01028", "symbol": "GODREJCP"},
    {"instrument_key": "NSE_EQ|INE196A01026", "symbol": "MARICO"},
    {"instrument_key": "NSE_EQ|INE259A01022", "symbol": "COLPAL"},
    {"instrument_key": "NSE_EQ|INE628A01036", "symbol": "BERGEPAINT"},
    {"instrument_key": "NSE_EQ|INE318A01026", "symbol": "PIDILITIND"},
    {"instrument_key": "NSE_EQ|INE079A01024", "symbol": "AMBUJACEM"},
    {"instrument_key": "NSE_EQ|INE012A01025", "symbol": "ACC"},
    {"instrument_key": "NSE_EQ|INE437A01024", "symbol": "APOLLOHOSP"},
    {"instrument_key": "NSE_EQ|INE192A01025", "symbol": "TATACONSUM"},
    {"instrument_key": "NSE_EQ|INE726G01019", "symbol": "ICICIPRULI"},
    {"instrument_key": "NSE_EQ|INE123W01016", "symbol": "SBILIFE"},
    {"instrument_key": "NSE_EQ|INE127D01025", "symbol": "HDFCAMC"},
    {"instrument_key": "NSE_EQ|INE663F01024", "symbol": "NAUKRI"},
    {"instrument_key": "NSE_EQ|INE545U01014", "symbol": "BANDHANBNK"},
    {"instrument_key": "NSE_EQ|INE171A01029", "symbol": "FEDERALBNK"},
    {"instrument_key": "NSE_EQ|INE020B01018", "symbol": "RECLTD"},
    {"instrument_key": "NSE_EQ|INE111A01025", "symbol": "CONCOR"},
    {"instrument_key": "NSE_EQ|INE121A01024", "symbol": "CHOLAFIN"},
    {"instrument_key": "NSE_EQ|INE376G01013", "symbol": "BIOCON"},
    {"instrument_key": "NSE_EQ|INE326A01037", "symbol": "LUPIN"},
    {"instrument_key": "NSE_EQ|INE685A01028", "symbol": "TORNTPHARM"},
    {"instrument_key": "NSE_EQ|INE406A01037", "symbol": "AUROPHARMA"},
    {"instrument_key": "NSE_EQ|INE571A01020", "symbol": "IPCALAB"},
    {"instrument_key": "NSE_EQ|INE323A01026", "symbol": "BOSCHLTD"},
    {"instrument_key": "NSE_EQ|INE053A01029", "symbol": "INDHOTEL"},
    {"instrument_key": "NSE_EQ|INE414G01012", "symbol": "MUTHOOTFIN"},
    {"instrument_key": "NSE_EQ|INE018E01016", "symbol": "SBICARD"},
    {"instrument_key": "NSE_EQ|INE335Y01020", "symbol": "IRCTC"},
    {"instrument_key": "NSE_EQ|INE192R01011", "symbol": "DMART"},
    {"instrument_key": "NSE_EQ|INE101B01010", "symbol": "MCDOWELL-N"},
    {"instrument_key": "NSE_EQ|INE813H01021", "symbol": "TORNTPOWER"},
    {"instrument_key": "NSE_EQ|INE140A01024", "symbol": "PEL"},
    {"instrument_key": "NSE_EQ|INE761H01022", "symbol": "PAGEIND"},
    # ── Popular Midcaps ────────────────────────────────────────────────────────
    {"instrument_key": "NSE_EQ|INE935N01020", "symbol": "DIXON"},
    {"instrument_key": "NSE_EQ|INE849A01020", "symbol": "TRENT"},
    {"instrument_key": "NSE_EQ|INE455K01017", "symbol": "POLYCAB"},
    {"instrument_key": "NSE_EQ|INE006I01046", "symbol": "ASTRAL"},
    {"instrument_key": "NSE_EQ|INE262H01021", "symbol": "PERSISTENT"},
    {"instrument_key": "NSE_EQ|INE591G01017", "symbol": "COFORGE"},
    {"instrument_key": "NSE_EQ|INE356A01018", "symbol": "MPHASIS"},
    {"instrument_key": "NSE_EQ|INE600L01024", "symbol": "LALPATHLAB"},
    {"instrument_key": "NSE_EQ|INE540L01014", "symbol": "ALKEM"},
    {"instrument_key": "NSE_EQ|INE010B01027", "symbol": "ZYDUSLIFE"},
    {"instrument_key": "NSE_EQ|INE393H01010", "symbol": "METROPOLIS"},
    {"instrument_key": "NSE_EQ|INE769A01020", "symbol": "AARTIIND"},
    {"instrument_key": "NSE_EQ|INE020B01018", "symbol": "RECLTD"},
    {"instrument_key": "NSE_EQ|INE733E01010", "symbol": "NTPC"},
    {"instrument_key": "NSE_EQ|INE245A01021", "symbol": "CUMMINSIND"},
    {"instrument_key": "NSE_EQ|INE860A01027", "symbol": "HCLTECH"},
    {"instrument_key": "NSE_EQ|INE584A01023", "symbol": "KAJARIACER"},
    {"instrument_key": "NSE_EQ|INE093I01010", "symbol": "PHOENIXLTD"},
    {"instrument_key": "NSE_EQ|INE242A01010", "symbol": "TVSMOTOR"},
    {"instrument_key": "NSE_EQ|INE089A01031", "symbol": "DRREDDY"},
    {"instrument_key": "NSE_EQ|INE722A01011", "symbol": "SUNDARMFIN"},
    {"instrument_key": "NSE_EQ|INE117A01022", "symbol": "ABB"},
    {"instrument_key": "NSE_EQ|INE669C01036", "symbol": "TECHM"},
    {"instrument_key": "NSE_EQ|INE205A01025", "symbol": "MOTHERSON"},
    {"instrument_key": "NSE_EQ|INE053A01029", "symbol": "INDHOTEL"},
    {"instrument_key": "NSE_EQ|INE274J01014", "symbol": "CDSL"},
    {"instrument_key": "NSE_EQ|INE148I01020", "symbol": "CAMS"},
    {"instrument_key": "NSE_EQ|INE121H01027", "symbol": "MAXHEALTH"},
    {"instrument_key": "NSE_EQ|INE070A01015", "symbol": "PATANJALI"},
    {"instrument_key": "NSE_EQ|INE040H01021", "symbol": "GLAND"},
    {"instrument_key": "NSE_EQ|INE152A01029", "symbol": "BPCL"},
    {"instrument_key": "NSE_EQ|INE671H01015", "symbol": "LICI"},
    {"instrument_key": "NSE_EQ|INE733E01010", "symbol": "NTPC"},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _enrich_with_live(instrument_key: str, intraday_candles: list, swing_candles: list):
    """
    Fetch the live quote and append synthetic current candles so indicators
    reflect the latest price rather than the last completed historical bar.

    Intraday: appends a virtual 5-min candle whose close = LTP.
    Swing   : replaces / appends today's daily candle using live day-OHLC + LTP.
    """
    try:
        quote_data = await upstox.get_live_quote([instrument_key])
        # Key in the response matches the instrument_key; fall back to first value if needed
        inst_data = quote_data.get(instrument_key) or next(iter(quote_data.values()), None)
        if not inst_data:
            return intraday_candles, swing_candles

        ltp = inst_data.get("last_price")
        if not ltp:
            return intraday_candles, swing_candles

        ltp = float(ltp)
        ohlc = inst_data.get("ohlc") or {}
        day_volume = float(inst_data.get("volume") or 0)
        now_ist = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+05:30")
        today_date = datetime.now().strftime("%Y-%m-%d")

        # ── Intraday synthetic 5-min candle ──────────────────────────────────
        if intraday_candles:
            last_close = float(sorted(intraday_candles, key=lambda c: c[0])[-1][4])
        else:
            last_close = ltp
        intraday_synthetic = [
            now_ist,
            last_close,
            max(ltp, last_close),
            min(ltp, last_close),
            ltp,
            0,   # volume unknown for current incomplete bar
            0,
        ]
        enriched_intraday = intraday_candles + [intraday_synthetic]

        # ── Swing synthetic daily candle ─────────────────────────────────────
        # Drop any existing partial today candle from the historical pull
        filtered_swing = [c for c in swing_candles if not str(c[0]).startswith(today_date)]
        swing_synthetic = [
            f"{today_date}T00:00:00+05:30",
            float(ohlc.get("open") or ltp),
            float(ohlc.get("high") or ltp),
            float(ohlc.get("low") or ltp),
            ltp,
            day_volume,
            0,
        ]
        enriched_swing = filtered_swing + [swing_synthetic]

        return enriched_intraday, enriched_swing

    except Exception:
        return intraday_candles, swing_candles


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    now = datetime.now()

    # 5-minute candles for the last 5 days
    intraday_from = _date_str(now - timedelta(days=5))
    intraday_to = _date_str(now)
    intraday_candles = await upstox.get_historical_candles(
        req.instrument_key, "5minute", intraday_from, intraday_to
    )

    # Daily candles for the last 180 days
    swing_from = _date_str(now - timedelta(days=180))
    swing_to = _date_str(now)
    swing_candles = await upstox.get_historical_candles(
        req.instrument_key, "1day", swing_from, swing_to
    )

    if not intraday_candles or not swing_candles:
        raise HTTPException(status_code=404, detail="No candle data returned from Upstox")

    # Enrich both candle lists with the current live price before computing indicators
    intraday_candles, swing_candles = await _enrich_with_live(
        req.instrument_key, intraday_candles, swing_candles
    )

    intraday_df = candles_to_df(intraday_candles)
    swing_df = candles_to_df(swing_candles)

    intraday_indicators = compute_all_indicators(intraday_df)
    swing_indicators = compute_all_indicators(swing_df)

    intraday_prediction = predict_intraday(intraday_df)
    swing_prediction = predict_swing(swing_df)

    intraday_signal = generate_intraday_signal(intraday_indicators, intraday_prediction)
    swing_signal = generate_swing_signal(swing_indicators, swing_prediction)

    return {
        "symbol": req.symbol,
        "instrument_key": req.instrument_key,
        "intraday": {
            "indicators": intraday_indicators,
            "prediction": intraday_prediction,
            "signal": intraday_signal,
            "candles": df_to_chart_data(intraday_df),
            "features_snapshot": get_features_snapshot(intraday_df),
        },
        "swing": {
            "indicators": swing_indicators,
            "prediction": swing_prediction,
            "signal": swing_signal,
            "candles": df_to_chart_data(swing_df),
            "features_snapshot": get_features_snapshot(swing_df),
        },
        "timestamp": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# Market scanner — two-phase approach
# ---------------------------------------------------------------------------

async def _batch_live_quotes(instrument_keys: list) -> dict:
    """Fetch live quotes in batches of 50; return combined {key: data} dict."""
    results: dict = {}
    for i in range(0, len(instrument_keys), 50):
        batch = instrument_keys[i : i + 50]
        try:
            data = await upstox.get_live_quote(batch)
            results.update(data)
        except Exception:
            pass
    return results


def _phase1_rank(universe: list, live_data: dict) -> list:
    """
    Phase 1 — score every stock by intraday momentum from a single live-quote call.
    Returns the universe sorted by momentum strength (biggest movers first).
    Change % is computed as abs((LTP - prev_close) / prev_close).
    """
    scored = []
    seen_keys = set()

    for inst in universe:
        key = inst["instrument_key"]
        if key in seen_keys:          # deduplicate
            continue
        seen_keys.add(key)

        q = live_data.get(key)
        if not q:
            # No live quote — put at back with score 0
            scored.append({"inst": inst, "change_pct": 0.0, "ltp": 0.0})
            continue

        ltp = float(q.get("last_price") or 0)
        ohlc = q.get("ohlc") or {}
        prev_close = float(ohlc.get("close") or ltp or 1)
        change_pct = abs((ltp - prev_close) / prev_close * 100) if prev_close else 0.0

        scored.append({"inst": inst, "change_pct": round(change_pct, 3), "ltp": ltp})

    scored.sort(key=lambda x: -x["change_pct"])
    return scored


@app.post("/api/market-scan")
async def market_scan(req: MarketScanRequest):
    universe    = req.instruments or NSE_UNIVERSE
    max_cands   = min(req.max_candidates, len(universe))
    now         = datetime.now()

    # ── Phase 1: live-quote filter ────────────────────────────────────────────
    all_keys    = [inst["instrument_key"] for inst in universe]
    live_data   = await _batch_live_quotes(all_keys)

    ranked      = _phase1_rank(universe, live_data)
    # Take the top movers; always include at least 20 even if they have no quote
    candidates  = [r["inst"] for r in ranked[:max_cands]]
    phase1_meta = [
        {"symbol": r["inst"]["symbol"], "change_pct": r["change_pct"]}
        for r in ranked[:max_cands]
    ]

    # ── Phase 2: deep analysis on candidates ──────────────────────────────────
    semaphore    = asyncio.Semaphore(5)
    intraday_from = _date_str(now - timedelta(days=5))
    intraday_to   = _date_str(now)
    swing_from    = _date_str(now - timedelta(days=180))
    swing_to      = _date_str(now)

    async def analyze_one(inst):
        async with semaphore:
            try:
                intraday_candles = await upstox.get_historical_candles(
                    inst["instrument_key"], "5minute", intraday_from, intraday_to
                )
                swing_candles = await upstox.get_historical_candles(
                    inst["instrument_key"], "1day", swing_from, swing_to
                )
                if not intraday_candles or not swing_candles:
                    return None

                # Enrich with live price for accuracy
                intraday_candles, swing_candles = await _enrich_with_live(
                    inst["instrument_key"], intraday_candles, swing_candles
                )

                intraday_df  = candles_to_df(intraday_candles)
                swing_df     = candles_to_df(swing_candles)

                intraday_ind = compute_all_indicators(intraday_df)
                swing_ind    = compute_all_indicators(swing_df)

                intraday_pred = predict_intraday(intraday_df)
                swing_pred    = predict_swing(swing_df)

                intraday_sig  = generate_intraday_signal(intraday_ind, intraday_pred)
                swing_sig     = generate_swing_signal(swing_ind, swing_pred)

                combined_score = intraday_sig.get("score", 0) + swing_sig.get("score", 0)

                # Attach Phase-1 momentum info
                p1 = next((r for r in ranked if r["inst"]["instrument_key"] == inst["instrument_key"]), {})

                return {
                    "symbol":          inst["symbol"],
                    "instrument_key":  inst["instrument_key"],
                    "combined_score":  combined_score,
                    "change_pct":      p1.get("change_pct", 0.0),
                    "ltp":             p1.get("ltp", intraday_ind.get("current_price")),
                    "intraday": {
                        "indicators": intraday_ind,
                        "prediction": intraday_pred,
                        "signal":     intraday_sig,
                    },
                    "swing": {
                        "indicators": swing_ind,
                        "prediction": swing_pred,
                        "signal":     swing_sig,
                    },
                }
            except Exception:
                return None

    results = await asyncio.gather(*[analyze_one(inst) for inst in candidates])
    valid   = [r for r in results if r is not None]

    buy_suggestions = sorted(
        [r for r in valid if r["swing"]["signal"]["signal"] == "BUY"],
        key=lambda x: -x["combined_score"],
    )[: req.max_results]

    sell_suggestions = sorted(
        [r for r in valid if r["swing"]["signal"]["signal"] == "SELL"],
        key=lambda x: x["combined_score"],
    )[: req.max_results]

    return {
        "buy_suggestions":  buy_suggestions,
        "sell_suggestions": sell_suggestions,
        "scanned":          len(valid),
        "universe_size":    len(universe),
        "candidates":       len(candidates),
        "phase1_movers":    phase1_meta[:10],   # top 10 movers for display
        "timestamp":        now.isoformat(),
    }


# ---------------------------------------------------------------------------
# Scanner AI report
# ---------------------------------------------------------------------------

class ScannerReportRequest(BaseModel):
    buy_suggestions:  list
    sell_suggestions: list


@app.post("/api/scanner-ai-report")
async def scanner_ai_report(req: ScannerReportRequest):
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")

    def _fmt(stocks: list, label: str) -> str:
        if not stocks:
            return f"{label}: none found\n"
        lines = [f"{label}:"]
        for s in stocks:
            sig   = s.get("swing", {}).get("signal", {})
            ind   = s.get("intraday", {}).get("indicators", {})
            pred  = s.get("swing", {}).get("prediction", {})
            lines.append(
                f"  • {s['symbol']}  score={s.get('combined_score')}/14"
                f"  RSI={ind.get('rsi')}  VWAP={'above' if ind.get('above_vwap') else 'below'}"
                f"  ML={pred.get('direction')}({pred.get('confidence')})"
                f"  move={s.get('change_pct', 0):.2f}%today"
                f"  entry={sig.get('entry')}  target={sig.get('target')}  SL={sig.get('stop_loss')}"
                f"  R:R={sig.get('risk_reward')}"
            )
        return "\n".join(lines)

    buy_block  = _fmt(req.buy_suggestions,  "BUY candidates")
    sell_block = _fmt(req.sell_suggestions, "AVOID candidates")

    prompt = f"""You are a sharp NSE stock analyst. Based on today's technical scan results below,
write a concise market report with two sections:

1. STOCKS TO BUY — for each buy candidate, one sentence on WHY it looks attractive right now
   (mention the specific indicator that stands out: RSI level, VWAP position, ML prediction, momentum).
2. STOCKS TO AVOID — for each avoid candidate, one sentence on WHY it looks weak or risky.

Keep the total report under 220 words. Be direct. No generic disclaimers. Use plain English.
Format each stock as a bullet point starting with the symbol in bold.

--- SCAN DATA ---
{buy_block}

{sell_block}
"""

    headers = {
        "x-api-key":          ANTHROPIC_API_KEY,
        "anthropic-version":  "2023-06-01",
        "content-type":       "application/json",
    }
    payload = {
        "model":      ANTHROPIC_MODEL,
        "max_tokens": 500,
        "messages":   [{"role": "user", "content": prompt}],
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=60)

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    result = resp.json()
    text   = "".join(block.get("text", "") for block in result.get("content", []))
    return {"report": text}


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

@app.get("/api/search")
async def search(q: str, exchange: str = "NSE"):
    results = await upstox.search_instruments(q, exchange)
    return {"results": results}


@app.get("/api/quote")
async def quote(keys: str):
    instrument_keys = [k.strip() for k in keys.split(",") if k.strip()]
    data = await upstox.get_live_quote(instrument_keys)
    return {"data": data}


@app.get("/api/market-status")
async def market_status():
    data = await upstox.get_market_status()
    return {"data": data}


# ---------------------------------------------------------------------------
# Paper trading
# ---------------------------------------------------------------------------

@app.get("/api/paper-trades")
def get_paper_trades():
    return {
        "trades": paper_trade.get_all_trades(),
        "summary": paper_trade.get_summary(),
    }


@app.post("/api/paper-trades")
def create_paper_trade(req: PaperTradeRequest):
    trade = paper_trade.add_trade(
        symbol=req.symbol,
        signal=req.signal,
        entry=req.entry,
        target=req.target,
        stop_loss=req.stop_loss,
        trade_type=req.type,
        instrument_key=req.instrument_key,
        features_snapshot=req.features_snapshot,
    )
    return trade


@app.put("/api/paper-trades/{trade_id}/exit")
def exit_paper_trade(trade_id: str, req: ExitTradeRequest):
    try:
        trade = paper_trade.exit_trade(trade_id, req.exit_price)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return trade


# ---------------------------------------------------------------------------
# Feedback stats & retraining
# ---------------------------------------------------------------------------

@app.get("/api/feedback-stats")
def feedback_stats():
    return paper_trade.get_feedback_stats()


class FeedbackRetrainRequest(BaseModel):
    instrument_key: str = None
    symbol: str = None


@app.post("/api/train-feedback")
async def train_feedback(req: FeedbackRetrainRequest):
    samples = paper_trade.get_feedback_samples()
    if not samples:
        raise HTTPException(status_code=400, detail="No resolved feedback samples yet. Close some paper trades first.")

    stats = paper_trade.get_feedback_stats()
    if not stats["ready_to_retrain"]:
        raise HTTPException(
            status_code=400,
            detail=f"Need at least 10 resolved trades to retrain. Have {stats['total']} so far.",
        )

    # Optionally blend with current stock's candle history
    base_df = None
    if req.instrument_key:
        try:
            now = datetime.now()
            candles = await upstox.get_historical_candles(
                req.instrument_key, "1day",
                _date_str(now - timedelta(days=180)),
                _date_str(now),
            )
            if candles:
                from indicators import candles_to_df
                base_df = candles_to_df(candles)
        except Exception:
            pass

    results = retrain_with_feedback(samples, base_df)
    return {"results": results, "feedback_used": len(samples)}


# ---------------------------------------------------------------------------
# Model training
# ---------------------------------------------------------------------------

@app.post("/api/train")
async def train(req: TrainRequest):
    now = datetime.now()
    from_date = _date_str(now - timedelta(days=180))
    to_date = _date_str(now)

    intraday_candles = await upstox.get_historical_candles(
        req.instrument_key, req.interval, from_date, to_date
    )
    daily_candles = await upstox.get_historical_candles(
        req.instrument_key, "1day", from_date, to_date
    )

    if not intraday_candles or not daily_candles:
        raise HTTPException(status_code=404, detail="No candle data returned from Upstox")

    intraday_df = candles_to_df(intraday_candles)
    daily_df = candles_to_df(daily_candles)

    intraday_metrics = train_intraday_model(intraday_df)
    swing_metrics = train_swing_model(daily_df)

    return {
        "intraday": intraday_metrics,
        "swing": swing_metrics,
    }


# ---------------------------------------------------------------------------
# AI Analyst
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


@app.post("/api/ai-analyst")
async def ai_analyst(req: AIAnalystRequest):
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY is not configured")

    data = req.analysis
    symbol = data.get("symbol", "this stock")
    intraday = data.get("intraday", {})
    swing = data.get("swing", {})

    prompt = (
        f"You are a stock market analyst. Based on the following technical data for {symbol}, "
        "write a concise (under 150 words) plain-language summary of the intraday and swing "
        "outlook, highlighting the key signals and risks. Do not give financial advice "
        "disclaimers beyond a brief note.\n\n"
        f"Intraday indicators: {intraday.get('indicators')}\n"
        f"Intraday ML prediction: {intraday.get('prediction')}\n"
        f"Intraday signal: {intraday.get('signal')}\n\n"
        f"Swing indicators: {swing.get('indicators')}\n"
        f"Swing ML prediction: {swing.get('prediction')}\n"
        f"Swing signal: {swing.get('signal')}\n"
    )

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 400,
        "messages": [{"role": "user", "content": prompt}],
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=60)

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    result = response.json()
    text = "".join(block.get("text", "") for block in result.get("content", []))

    return {"analysis": text}


# ---------------------------------------------------------------------------
# WebSocket live feed
# ---------------------------------------------------------------------------

@app.websocket("/ws/feed")
async def ws_feed(websocket: WebSocket):
    await websocket.accept()

    stream_task = None

    try:
        init_message = await websocket.receive_json()
        instrument_keys = init_message.get("instrument_keys", [])

        async def forward_tick(data):
            await websocket.send_json(data)

        stream_task = asyncio.create_task(upstox.stream_market_feed(instrument_keys, forward_tick))

        # Wait until the stream task ends or the client disconnects
        while True:
            done, _ = await asyncio.wait({stream_task}, timeout=1.0)
            if stream_task in done:
                break
            try:
                # Drain any incoming messages (e.g. ping/close) without blocking
                await asyncio.wait_for(websocket.receive_text(), timeout=0.01)
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_json({"error": str(exc)})
        except Exception:
            pass
    finally:
        if stream_task and not stream_task.done():
            stream_task.cancel()
        try:
            await websocket.close()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)
