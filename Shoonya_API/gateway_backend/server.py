"""FastAPI server exposing Shoonya broker data to the Gateway frontend."""

import logging
import os
from typing import Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect

logging.basicConfig(level=logging.INFO)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from shoonya_auth import ShonyaAuthenticator
from shoonya_logout import logout as shoonya_logout
from user_details import get_user_details
from search_scrip import search_scrip
from option_chain import get_option_chain
from shoonya_ws import ws_manager
from scripmaster import get_nfo_df

app = FastAPI(title="Gateway API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_auth: Optional[ShonyaAuthenticator] = None


def _require_auth() -> ShonyaAuthenticator:
    if _auth is None or not _auth.is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated with Shoonya broker")
    return _auth


@app.post("/api/connect")
def connect():
    global _auth
    auth = ShonyaAuthenticator()
    result = auth.authenticate()
    if result["success"]:
        _auth = auth
        ws_manager.set_credentials(auth.user_id, auth.auth_token)
        return {"connected": True, "method": "rest", "message": result["message"]}
    raise HTTPException(status_code=401, detail=result["message"])


@app.post("/api/disconnect")
async def disconnect():
    global _auth
    if _auth is not None and _auth.is_authenticated():
        shoonya_logout(_auth.user_id, _auth.auth_token)
    await ws_manager.shutdown()
    _auth = None
    return {"connected": False}


@app.get("/api/status")
def status():
    connected = _auth is not None and _auth.is_authenticated()
    return {"connected": connected, "method": "rest" if connected else "none"}


class SearchRequest(BaseModel):
    stext: str
    exch: Optional[str] = None


@app.post("/api/search")
def search(req: SearchRequest):
    auth = _require_auth()
    try:
        data = search_scrip(auth.user_id, auth.auth_token, req.stext, req.exch)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Shoonya API error: {e}")
    if data.get("stat") != "Ok":
        raise HTTPException(status_code=400, detail=data.get("emsg", "Search failed"))
    return {"values": data.get("values", [])}


class OptionChainRequest(BaseModel):
    symbol: str
    exchange: str
    expiry: Optional[str] = None
    underlying_token: Optional[str] = None  # spot/index token for ATM price lookup
    strikeprice: Optional[float] = None     # explicit ATM override
    count: int = 15                         # strikes above + below ATM


@app.post("/api/option-chain")
def option_chain(req: OptionChainRequest):
    auth = _require_auth()
    try:
        data = get_option_chain(
            auth.user_id, auth.auth_token,
            req.symbol, req.exchange, req.expiry,
            req.underlying_token, req.strikeprice, req.count,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Shoonya API error: {e}")
    if "error" in data:
        raise HTTPException(status_code=400, detail=data["error"])
    return data


@app.post("/api/scripmaster/refresh")
def refresh_scripmaster():
    _require_auth()
    try:
        df = get_nfo_df(force_refresh=True)
        return {"refreshed": True, "rows": len(df)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Scripmaster refresh failed: {e}")


@app.websocket("/ws/market-data")
async def market_data_ws(ws: WebSocket):
    if _auth is None or not _auth.is_authenticated():
        await ws.close(code=4001, reason="Not authenticated")
        return

    await ws.accept()
    await ws_manager.add_client(ws)

    try:
        while True:
            msg = await ws.receive_json()
            action = msg.get("action")
            tokens = msg.get("tokens", [])
            sub_type = msg.get("type", "touchline")

            try:
                if action == "subscribe":
                    if sub_type == "depth":
                        await ws_manager.subscribe_depth(tokens)
                    else:
                        await ws_manager.subscribe_touchline(tokens)
                elif action == "unsubscribe":
                    if sub_type == "depth":
                        await ws_manager.unsubscribe_depth(tokens)
                    else:
                        await ws_manager.unsubscribe_touchline(tokens)
            except Exception as e:
                # Shoonya WS may be temporarily down — don't close the frontend connection
                await ws.send_json({"t": "error", "msg": str(e)})
    except WebSocketDisconnect:
        ws_manager.remove_client(ws)
    except Exception:
        ws_manager.remove_client(ws)
        try:
            await ws.close()
        except Exception:
            pass


@app.get("/api/user")
def user_details():
    auth = _require_auth()
    try:
        data = get_user_details(auth.user_id, auth.auth_token)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Shoonya API error: {e}")
    if data.get("stat") != "Ok":
        raise HTTPException(status_code=400, detail=data.get("emsg", "Failed to fetch user details"))
    return {
        "uid": data.get("uid", ""),
        "actid": data.get("actid", ""),
        "email": data.get("email", ""),
        "m_num": data.get("m_num", ""),
        "brkname": data.get("brkname", ""),
        "brnchid": data.get("brnchid", ""),
        "uprev": data.get("uprev", ""),
        "exarr": data.get("exarr", []),
        "orarr": data.get("orarr", []),
        "prarr": data.get("prarr", []),
        "request_time": data.get("request_time", ""),
    }
