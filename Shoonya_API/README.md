# Shoonya API Gateway

A local trading gateway that connects to the [Shoonya (Finvasia)](https://shoonya.com) broker API and serves live option chain data to a React frontend.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    React Frontend                   │
│  App.tsx · OptionChain.tsx · useMarketWebSocket.ts  │
└────────────────┬───────────────────┬────────────────┘
                 │  REST (HTTP)      │  WebSocket
                 ▼                  ▼
┌─────────────────────────────────────────────────────┐
│              FastAPI Backend  :8000                 │
│                   server.py                         │
│                                                     │
│  /api/connect      /api/status      /api/user       │
│  /api/disconnect   /api/search      /api/option-chain│
│  /api/scripmaster/refresh                           │
│  /ws/market-data  (WebSocket fan-out)               │
└──┬────────────────────────────────────────┬─────────┘
   │  REST calls                            │  WebSocket
   ▼                                        ▼
Shoonya REST API              Shoonya WebSocket
NorenWClientAPI/              wss://api.shoonya.com/
```

The backend is the single point of contact with Shoonya. The frontend never touches the broker API directly.

---

## How authentication works

Shoonya uses an OAuth-style flow. A session token (`susertoken`) is valid for one calendar day.

```
get_authcode.py          shoonya_auth.py
───────────────          ───────────────
Headless Chrome  ──────► POST /GenAcsTok
(Selenium)                 jData = { code, checksum }
  ↓                        checksum = sha256(vendor_code + secret + oauth_code)
OAuth code               ↓
from redirect URL      susertoken  ←─ cached in token_store.json
```

On startup the backend checks `token_store.json` for a token issued today. If one exists it skips the browser login entirely. The OAuth code itself is also cached — if the session token request fails (e.g. the code was already consumed), the cached code is cleared so the next attempt does a fresh browser login.

**Relevant files:**
- [gateway_backend/get_authcode.py](gateway_backend/get_authcode.py) — Selenium headless Chrome login, extracts `code=...` from the redirect URL
- [gateway_backend/shoonya_auth.py](gateway_backend/shoonya_auth.py) — `ShonyaAuthenticator` class, token caching, `POST /GenAcsTok`

---

## Option chain pipeline

The diagram above shows the two-stage pipeline used to build the option chain table.

### Stage 1 — Scripmaster path (NFO, primary)

```
get_nfo_df()                     build_token_map()
─────────────                    ─────────────────
Download NFO_symbols.txt.zip  →  Filter by symbol + expiry
Parse CSV → DataFrame            Build two dicts:
Cache as scripmaster_nfo.csv       token_map  { "NFO|41234": {token, tsym, ...} }
Refreshed once per day             strike_map { 50000.0: {CE: "41234", PE: "41235"} }
                                        ↓
                               get_quote() on underlying token → ATM price
                                        ↓
                               Slice ±count strikes around ATM
                                        ↓
                               Parallel GetQuotes (ThreadPoolExecutor, 20 workers)
                               Initial price snapshot for each leg
```

### Stage 2 — REST fallback (non-NFO or scripmaster failure)

```
search_scrip()  →  get_option_chain_api()  →  parallel get_quote()
SearchScrip        GetOptionChain              GetQuotes
  ↓                  ↓
Find futures       CE/PE pairs around ATM
contract for       (calls Shoonya's own
the expiry         option chain endpoint)
```

**Relevant files:**
- [gateway_backend/scripmaster.py](gateway_backend/scripmaster.py) — download, parse, cache NFO scripmaster; `get_nfo_df()`, `get_expiries()`, `build_token_map()`
- [gateway_backend/option_chain.py](gateway_backend/option_chain.py) — orchestrates both paths; `get_option_chain()` is the public entry point
- [gateway_backend/get_quote.py](gateway_backend/get_quote.py) — `POST /GetQuotes` for a single token
- [gateway_backend/get_option_chain_api.py](gateway_backend/get_option_chain_api.py) — `POST /GetOptionChain` (Shoonya's REST endpoint)
- [gateway_backend/search_scrip.py](gateway_backend/search_scrip.py) — `POST /SearchScrip`

---

## WebSocket fan-out

One persistent Shoonya WebSocket connection is shared across all connected browser tabs.

```
ShoonyaWSManager (shoonya_ws.py)
│
├── _connect_shoonya()   open wss://api.shoonya.com/NorenWSTP/?access_token=...
│                        wait for {"t":"ck","s":"Ok"} ack
│
├── _listen()            read raw ticks → update chain_dict → _broadcast()
│   auto-reconnect       on drop: sleep 5s → reconnect if clients still present
│
├── subscribe_touchline() → send {"t":"t","k":"NFO|41234#NFO|41235"}
├── subscribe_depth()     → send {"t":"d","k":"NFO|41234"}
├── unsubscribe_*()       → send {"t":"u"/"ud","k":...}
│
└── chain_dict            in-memory tick cache { "41234": {lp, oi, v, ...} }
                          partial updates are merged (Shoonya sends diffs)
```

Frontend connects to `ws://localhost:8000/ws/market-data`. Server-side, `server.py` registers the client with `ws_manager` and proxies subscribe/unsubscribe messages through to Shoonya.

**Relevant files:**
- [gateway_backend/shoonya_ws.py](gateway_backend/shoonya_ws.py) — `ShoonyaWSManager` singleton
- [frontend/src/useMarketWebSocket.ts](frontend/src/useMarketWebSocket.ts) — React hook; exponential backoff reconnect (max 22s), merges partial tick frames into a `PricesMap`

---

## Frontend

Built with React 19 + Vite + Tailwind CSS 4.

| File | Role |
|---|---|
| `App.tsx` | Auth flow (connect/disconnect), user info panel, mounts `<OptionChain>` |
| `OptionChain.tsx` | Renders the CE/PE strike table; overlays live WebSocket prices on top of the REST snapshot |
| `useMarketWebSocket.ts` | WebSocket connection management + `subscribe`/`unsubscribe` helpers |

The option chain table gets an initial price snapshot from the REST `POST /api/option-chain` response, then live prices stream in over WebSocket and replace those values in real time without re-fetching.

---

## Project structure

```
Shoonya_API/
├── gateway_backend/
│   ├── server.py                 FastAPI app, all HTTP + WS endpoints
│   ├── shoonya_auth.py           OAuth login, token caching
│   ├── get_authcode.py           Selenium browser automation
│   ├── shoonya_logout.py         POST /Logout
│   ├── shoonya_ws.py             WebSocket manager (singleton)
│   ├── option_chain.py           Option chain builder (scripmaster + REST fallback)
│   ├── scripmaster.py            NFO scripmaster download + cache
│   ├── get_quote.py              POST /GetQuotes
│   ├── get_option_chain_api.py   POST /GetOptionChain
│   ├── search_scrip.py           POST /SearchScrip
│   ├── user_details.py           POST /UserDetails
│   ├── requirements.txt
│   ├── .env.example
│   └── tests/
│       ├── test_option_chain.py
│       ├── test_search_scrip.py
│       ├── test_get_quote.py
│       ├── test_get_option_chain_api.py
│       ├── test_scripmaster.py
│       └── test_shoonya_ws.py
└── frontend/
    ├── src/
    │   ├── App.tsx
    │   ├── OptionChain.tsx
    │   └── useMarketWebSocket.ts
    ├── package.json
    └── vite.config.ts
```

---

## Setup

### 1. Environment variables

Copy `.env.example` to `.env` in `gateway_backend/` and fill in your credentials:

```
SHONYA_USER_ID=        # your Shoonya login ID
SHONYA_PASSWORD=       # account password
SHONYA_TWO_FA=         # TOTP secret (not the OTP — the base32 secret)
SHONYA_VENDOR_CODE=    # app/vendor code from the Shoonya portal
SHONYA_API_SECRET=     # secret key from the Shoonya portal
SHOONYA_API_HOST=https://api.shoonya.com/NorenWClientAPI
SHOONYA_WS_URL=wss://api.shoonya.com/NorenWSTP/
```

### 2. Backend

```bash
cd gateway_backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --reload --port 8000
```

On first `POST /api/connect`, the backend opens a headless Chrome window, logs in to Shoonya, and caches the session token. Subsequent connects within the same day reuse the cached token.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
```

Vite proxies `/api` and `/ws` to `localhost:8000` in dev mode.

---

## API reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/connect` | Authenticate with Shoonya (browser login + GenAcsTok) |
| `POST` | `/api/disconnect` | Logout and tear down WebSocket |
| `GET` | `/api/status` | `{ connected: bool }` |
| `GET` | `/api/user` | User profile from Shoonya |
| `POST` | `/api/search` | `{ stext, exch? }` → instrument search |
| `POST` | `/api/option-chain` | `{ symbol, exchange, expiry?, count? }` → chain snapshot |
| `POST` | `/api/scripmaster/refresh` | Force re-download NFO scripmaster |
| `WS` | `/ws/market-data` | Live tick stream; send `{ action, type, tokens }` to subscribe |

WebSocket subscribe message format:

```json
{ "action": "subscribe", "type": "touchline", "tokens": [{ "exch": "NFO", "token": "41234" }] }
```
