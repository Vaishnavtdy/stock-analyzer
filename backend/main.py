import asyncio
import os
from datetime import datetime, timedelta
from typing import Any, Dict

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
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
