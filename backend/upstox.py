import json
from urllib.parse import quote

import httpx
import websockets

from auth import get_token

BASE_URL = "https://api.upstox.com/v2"
FEED_WS_URL = "wss://api.upstox.com/v2/feed/market-data-feed"


def _headers():
    return {
        "Authorization": f"Bearer {get_token()}",
        "Accept": "application/json",
    }


async def get_historical_candles(instrument_key: str, interval: str, from_date: str, to_date: str):
    """
    interval: one of 1minute, 5minute, 15minute, 30minute, 1day
    Returns list of [timestamp, open, high, low, close, volume, oi]
    """
    encoded_key = quote(instrument_key, safe="")
    url = f"{BASE_URL}/historical-candle/{encoded_key}/{interval}/{to_date}/{from_date}"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=_headers())
        response.raise_for_status()
        data = response.json()

    return data.get("data", {}).get("candles", [])


async def get_live_quote(instrument_keys: list):
    """Returns live LTP, OHLC, volume, change for given instrument keys."""
    joined_keys = ",".join(instrument_keys)
    url = f"{BASE_URL}/market-quote/quotes?instrument_key={quote(joined_keys, safe=',')}"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=_headers())
        response.raise_for_status()
        data = response.json()

    return data.get("data", {})


async def search_instruments(query: str, exchange: str = "NSE"):
    url = f"{BASE_URL}/instruments/search?q={quote(query)}&exchange={exchange}"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=_headers())
        response.raise_for_status()
        data = response.json()

    return data.get("data", [])


async def get_market_status():
    url = f"{BASE_URL}/market/status/NSE"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=_headers())
        response.raise_for_status()
        data = response.json()

    return data.get("data", {})


async def stream_market_feed(instrument_keys: list, callback):
    """
    Connects to Upstox's market data feed websocket and invokes `callback(data)`
    for every tick received until the connection is closed.
    """
    headers = {"Authorization": f"Bearer {get_token()}"}

    async with websockets.connect(FEED_WS_URL, extra_headers=headers) as ws:
        subscribe_message = {
            "guid": "marketpulse",
            "method": "sub",
            "data": {"mode": "full", "instrumentKeys": instrument_keys},
        }
        await ws.send(json.dumps(subscribe_message))

        async for message in ws:
            try:
                if isinstance(message, bytes):
                    data = json.loads(message.decode("utf-8"))
                else:
                    data = json.loads(message)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            await callback(data)
