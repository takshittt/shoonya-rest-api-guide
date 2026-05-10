"""Shoonya WebSocket manager — one persistent connection to Shoonya, fanned out to all frontend clients."""

import asyncio
import json
import logging
import os
from typing import Dict, Optional, Set

import websockets
from fastapi import WebSocket
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

SHOONYA_WS_URL = os.getenv("SHOONYA_WS_URL", "wss://api.shoonya.com/NorenWSTP/")
_RECONNECT_DELAY = 5  # seconds before retrying Shoonya WS after a drop


class ShoonyaWSManager:
    def __init__(self):
        self._shoonya_ws = None
        self._clients: Set[WebSocket] = set()
        self._listener_task: Optional[asyncio.Task] = None
        self._user_id: Optional[str] = None
        self._auth_token: Optional[str] = None
        self.connected = False
        self._connecting = False
        # Live tick cache keyed by bare token string e.g. "41234"
        # Shoonya sends partial updates; each tick is merged with prior state.
        self.chain_dict: Dict[str, Dict] = {}

    def set_credentials(self, user_id: str, auth_token: str, password: str = ""):
        self._user_id = user_id
        self._auth_token = auth_token

    async def _connect_shoonya(self):
        """Open the WebSocket to Shoonya and authenticate."""
        url = f"{SHOONYA_WS_URL}?access_token={self._auth_token}"
        self._shoonya_ws = await websockets.connect(url)
        log.info("Shoonya WS connected → uid=%s token_prefix=%s",
                 self._user_id, (self._auth_token or "")[:10])

        # Wait for broker ack {"t":"ck","s":"Ok"} — proceed anyway if it doesn't arrive
        try:
            raw = await asyncio.wait_for(self._shoonya_ws.recv(), timeout=8)
            resp = json.loads(raw)
            log.info("Shoonya WS ack: %s", resp)
            if resp.get("s") == "Ok":
                log.info("Shoonya WS authenticated")
            else:
                log.warning("Shoonya WS unexpected ack: %s — proceeding anyway", resp)
        except asyncio.TimeoutError:
            log.warning("Shoonya WS no ack within 8s — proceeding anyway")

        self.connected = True
        self._connecting = False
        log.info("Shoonya WS connected and authenticated")
        self._listener_task = asyncio.create_task(self._listen())

    async def _listen(self):
        """Read ticks from Shoonya and broadcast to all frontend clients. Reconnects on drop."""
        try:
            async for raw in self._shoonya_ws:
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                # Maintain chain_dict for touchline tick frames ('tf' = update, 'tk' = ack/snapshot)
                t_type = data.get("t")
                tk = data.get("tk")
                if t_type in ("tf", "tk") and tk:
                    prev = self.chain_dict.get(tk, {})
                    self.chain_dict[tk] = {**prev, **data}
                await self._broadcast(data)
        except Exception as exc:
            log.warning("Shoonya WS dropped: %s — will reconnect in %ss", exc, _RECONNECT_DELAY)
        finally:
            self.connected = False
            self._shoonya_ws = None
            # Schedule reconnect if we still have clients
            if self._clients:
                asyncio.create_task(self._delayed_reconnect())

    async def _delayed_reconnect(self):
        await asyncio.sleep(_RECONNECT_DELAY)
        if not self.connected and self._clients and self._user_id and self._auth_token:
            log.info("Reconnecting to Shoonya WS…")
            try:
                await self._connect_shoonya()
            except Exception as exc:
                log.error("Shoonya WS reconnect failed: %s", exc)
                # Will retry again if clients still present via the next _listen drop
                asyncio.create_task(self._delayed_reconnect())

    async def _broadcast(self, data: dict):
        dead: Set[WebSocket] = set()
        for client in list(self._clients):
            try:
                await client.send_json(data)
            except Exception:
                dead.add(client)
        self._clients -= dead

    # ── Client management ──────────────────────────────────────────────────────

    async def add_client(self, ws: WebSocket):
        """Register a frontend WS client. Lazily connects to Shoonya on the first client."""
        if not self.connected and not self._connecting:
            self._connecting = True
            try:
                await self._connect_shoonya()
            except Exception as exc:
                self._connecting = False
                log.error("Failed to connect to Shoonya WS: %s", exc)
                # Still add the client — reconnect loop will retry
        self._clients.add(ws)

    def remove_client(self, ws: WebSocket):
        self._clients.discard(ws)

    # ── Subscription helpers ────────────────────────────────────────────────────

    async def subscribe_touchline(self, tokens: list):
        if not self._shoonya_ws:
            raise RuntimeError("Shoonya WS not connected")
        k = "#".join(f"{t['exch']}|{t['token']}" for t in tokens)
        await self._shoonya_ws.send(json.dumps({"t": "t", "k": k}))

    async def subscribe_depth(self, tokens: list):
        if not self._shoonya_ws:
            raise RuntimeError("Shoonya WS not connected")
        k = "#".join(f"{t['exch']}|{t['token']}" for t in tokens)
        await self._shoonya_ws.send(json.dumps({"t": "d", "k": k}))

    async def unsubscribe_touchline(self, tokens: list):
        if not self._shoonya_ws:
            return
        k = "#".join(f"{t['exch']}|{t['token']}" for t in tokens)
        await self._shoonya_ws.send(json.dumps({"t": "u", "k": k}))

    async def unsubscribe_depth(self, tokens: list):
        if not self._shoonya_ws:
            return
        k = "#".join(f"{t['exch']}|{t['token']}" for t in tokens)
        await self._shoonya_ws.send(json.dumps({"t": "ud", "k": k}))

    def get_chain_snapshot(self, tokens: list) -> Dict[str, Dict]:
        """Return a copy of chain_dict entries for the given bare token strings."""
        return {tk: dict(self.chain_dict[tk]) for tk in tokens if tk in self.chain_dict}

    # ── Lifecycle ───────────────────────────────────────────────────────────────

    async def shutdown(self):
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        if self._shoonya_ws:
            await self._shoonya_ws.close()
        self._clients.clear()
        self.chain_dict.clear()
        self.connected = False
        self._shoonya_ws = None
        self._listener_task = None


# Module-level singleton — imported and used by server.py
ws_manager = ShoonyaWSManager()
