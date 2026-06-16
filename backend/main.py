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
from ml_model import predict_intraday, predict_swing, train_intraday_model, train_swing_model
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


class ExitTradeRequest(BaseModel):
    exit_price: float


class AIAnalystRequest(BaseModel):
    analysis: Dict[str, Any]


class MarketScanRequest(BaseModel):
    instruments: list = None
    max_results: int = 5


# Default Nifty 50 watchlist (instrument_key uses NSE_EQ|ISIN format)
NIFTY50_WATCHLIST = [
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
        },
        "swing": {
            "indicators": swing_indicators,
            "prediction": swing_prediction,
            "signal": swing_signal,
            "candles": df_to_chart_data(swing_df),
        },
        "timestamp": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# Market scanner
# ---------------------------------------------------------------------------

@app.post("/api/market-scan")
async def market_scan(req: MarketScanRequest):
    instruments = req.instruments or NIFTY50_WATCHLIST
    semaphore = asyncio.Semaphore(5)
    now = datetime.now()
    intraday_from = _date_str(now - timedelta(days=5))
    intraday_to = _date_str(now)
    swing_from = _date_str(now - timedelta(days=180))
    swing_to = _date_str(now)

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

                intraday_df = candles_to_df(intraday_candles)
                swing_df = candles_to_df(swing_candles)

                intraday_indicators = compute_all_indicators(intraday_df)
                swing_indicators = compute_all_indicators(swing_df)

                intraday_prediction = predict_intraday(intraday_df)
                swing_prediction = predict_swing(swing_df)

                intraday_signal = generate_intraday_signal(intraday_indicators, intraday_prediction)
                swing_signal = generate_swing_signal(swing_indicators, swing_prediction)

                combined_score = intraday_signal.get("score", 0) + swing_signal.get("score", 0)

                return {
                    "symbol": inst["symbol"],
                    "instrument_key": inst["instrument_key"],
                    "combined_score": combined_score,
                    "intraday": {
                        "indicators": intraday_indicators,
                        "prediction": intraday_prediction,
                        "signal": intraday_signal,
                    },
                    "swing": {
                        "indicators": swing_indicators,
                        "prediction": swing_prediction,
                        "signal": swing_signal,
                    },
                }
            except Exception:
                return None

    results = await asyncio.gather(*[analyze_one(inst) for inst in instruments])
    valid = [r for r in results if r is not None]

    buy_suggestions = sorted(
        [r for r in valid if r["swing"]["signal"]["signal"] == "BUY"],
        key=lambda x: -x["combined_score"],
    )[: req.max_results]

    sell_suggestions = sorted(
        [r for r in valid if r["swing"]["signal"]["signal"] == "SELL"],
        key=lambda x: x["combined_score"],
    )[: req.max_results]

    return {
        "buy_suggestions": buy_suggestions,
        "sell_suggestions": sell_suggestions,
        "scanned": len(valid),
        "total": len(instruments),
        "timestamp": now.isoformat(),
    }


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
