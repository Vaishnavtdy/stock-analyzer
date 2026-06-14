# MarketPulse Pro

Full-stack intraday + swing stock prediction system built on the Upstox API, a
FastAPI + XGBoost backend, and a React + Vite frontend.

## Features

- Upstox OAuth2 login flow
- Live market data via Upstox WebSocket feed
- Technical indicators: RSI, MACD, EMA(9/21/50), Bollinger Bands, VWAP, ATR,
  OBV, Stochastic, support/resistance, volume spike detection
- XGBoost ML models for intraday (next 5-min candle) and swing (3-day) direction
- Rule-based signal generator (BUY/SELL/NEUTRAL) with entry/target/stop-loss
  and risk:reward
- In-memory paper trading tracker with PnL and win-rate stats
- AI Analyst panel powered by the Anthropic API

## Backend setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in your Upstox + Anthropic credentials
uvicorn main:app --port 5000 --reload
```

### Authentication

1. `GET /login` returns an Upstox authorization URL — open it in a browser and log in.
2. Upstox redirects to `UPSTOX_REDIRECT_URI` (`/callback`) with a `code` query param,
   which the backend exchanges for an access token (stored in memory).
3. `GET /token-status` reports whether a valid token is currently stored.

> The access token is held in memory only and is cleared on server restart —
> repeat the login flow after restarting the backend.

## Frontend setup

```bash
cd frontend
npm install
npm run dev
```

The dev server runs at `http://localhost:5173` and talks to the backend at
`http://127.0.0.1:5000`.

## API overview

| Method | Path | Description |
| --- | --- | --- |
| GET | `/login` | Get Upstox OAuth authorization URL |
| GET | `/callback` | OAuth callback — exchanges code for access token |
| GET | `/token-status` | Check if Upstox token is stored |
| POST | `/api/analyze` | Run indicators, ML prediction and signal generation for a symbol |
| GET | `/api/search` | Search Upstox instruments |
| GET | `/api/quote` | Live quote for one or more instrument keys |
| GET | `/api/market-status` | NSE market status |
| GET | `/api/paper-trades` | List paper trades + summary |
| POST | `/api/paper-trades` | Open a new paper trade |
| PUT | `/api/paper-trades/{id}/exit` | Manually exit a paper trade |
| POST | `/api/train` | Retrain the intraday + swing XGBoost models |
| POST | `/api/ai-analyst` | Get an AI-generated narrative summary |
| WS | `/ws/feed` | Live tick stream proxied from Upstox |

## Project structure

```
marketpulse-pro/
├── backend/
│   ├── main.py          # FastAPI app, routes, websocket
│   ├── auth.py           # Upstox OAuth2 flow
│   ├── upstox.py          # Upstox REST + websocket client
│   ├── indicators.py      # Technical indicator calculations
│   ├── ml_model.py         # XGBoost training + prediction
│   ├── signals.py          # Signal scoring/generation
│   ├── paper_trade.py       # In-memory paper trading tracker
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    ├── src/
    │   ├── components/      # Header, LiveTicker, CandleChart, panels, etc.
    │   ├── hooks/            # useWebSocket, useAI
    │   ├── api.js            # Shared axios client
    │   ├── App.jsx
    │   └── App.css
    └── package.json
```

## Notes

- ML models are trained on demand (first prediction request auto-trains and
  caches the model under `backend/models/`) or explicitly via `POST /api/train`.
- The paper trading ledger is in-memory and resets on backend restart.
- `ANTHROPIC_API_KEY` (and optional `ANTHROPIC_MODEL`) power the AI Analyst panel.
