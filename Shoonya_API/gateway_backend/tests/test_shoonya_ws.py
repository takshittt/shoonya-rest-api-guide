"""Tests for shoonya_ws.py — Shoonya WebSocket manager.

Uses a real Shoonya WS connection (susertoken from GenAcsTok).
Tick-receive tests are best-effort: they SKIP gracefully outside market hours.
"""

import asyncio
import json
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shoonya_auth import ShonyaAuthenticator
from search_scrip import search_scrip
from shoonya_ws import ShoonyaWSManager

TICK_WAIT_SECONDS = 8   # how long to wait for a live tick before skipping


# ── Helpers ────────────────────────────────────────────────────────────────────

def _authenticate():
    auth = ShonyaAuthenticator()
    result = auth.authenticate()
    if not result["success"]:
        raise RuntimeError(f"Auth failed: {result['message']}")
    if not auth.auth_token:
        raise RuntimeError("No token available after authentication")
    return auth.user_id, auth.auth_token


def _get_token(user_id, token, symbol, exchange):
    """Return the first instrument token for a symbol via SearchScrip."""
    raw = search_scrip(user_id, token, symbol, exchange)
    if raw.get("stat") != "Ok":
        raise RuntimeError(f"SearchScrip failed for {symbol}/{exchange}: {raw.get('emsg')}")
    values = raw.get("values", [])
    if not values:
        raise RuntimeError(f"No instruments found for {symbol}/{exchange}")
    eq = next((v for v in values if v.get("instname", "").upper() in ("EQ", "INDEX")), values[0])
    return eq["token"]


class MockClient:
    """Minimal stand-in for a FastAPI WebSocket that records received messages."""
    def __init__(self):
        self.messages: list = []
        self._fail = False

    async def send_json(self, data: dict):
        if self._fail:
            raise RuntimeError("mock client disconnected")
        self.messages.append(data)


def _make_manager(user_id, ws_token) -> ShoonyaWSManager:
    mgr = ShoonyaWSManager()
    mgr.set_credentials(user_id, ws_token)
    return mgr


# ── Tests ──────────────────────────────────────────────────────────────────────

async def test_connect_and_auth(user_id, ws_token):
    """Manager connects to Shoonya WS and authenticates successfully."""
    print("\n--- Connect & auth test ---")
    mgr = _make_manager(user_id, ws_token)
    t0 = time.perf_counter()
    connected_ok = False
    try:
        await mgr._connect_shoonya()
        elapsed = time.perf_counter() - t0
        assert mgr.connected, "Expected manager.connected == True after connect"
        print(f"  PASS  connected=True  ({elapsed:.2f}s)")
        connected_ok = True
    finally:
        await mgr.shutdown()
        assert not mgr.connected, "Expected manager.connected == False after shutdown"
        if connected_ok:
            print(f"  PASS  shutdown clean  connected={mgr.connected}")


async def test_add_remove_client(user_id, ws_token):
    """add_client connects lazily; remove_client drops the client."""
    print("\n--- Add/remove client test ---")
    mgr = _make_manager(user_id, ws_token)
    client = MockClient()
    try:
        await mgr.add_client(client)
        assert client in mgr._clients, "Client not added to _clients set"
        assert mgr.connected, "Expected WS to connect on first client"
        print(f"  PASS  client added  connected={mgr.connected}  clients={len(mgr._clients)}")

        mgr.remove_client(client)
        assert client not in mgr._clients, "Client still in _clients after remove"
        print(f"  PASS  client removed  clients={len(mgr._clients)}")
    finally:
        await mgr.shutdown()


async def test_subscribe_touchline_sends_message(user_id, ws_token, inst_token):
    """subscribe_touchline sends the correct 't':'t' frame to Shoonya."""
    print(f"\n--- Subscribe touchline message test (token={inst_token}) ---")
    mgr = _make_manager(user_id, ws_token)
    sent_messages: list = []

    try:
        await mgr._connect_shoonya()

        # Patch the WS send to capture outgoing frames
        original_send = mgr._shoonya_ws.send
        async def recording_send(msg):
            sent_messages.append(json.loads(msg))
            return await original_send(msg)
        mgr._shoonya_ws.send = recording_send

        tokens = [{"exch": "NSE", "token": inst_token}]
        await mgr.subscribe_touchline(tokens)

        assert sent_messages, "No message was sent to Shoonya"
        msg = sent_messages[-1]
        assert msg.get("t") == "t", f"Expected t='t', got: {msg}"
        assert f"NSE|{inst_token}" in msg.get("k", ""), (
            f"Expected 'NSE|{inst_token}' in k field, got: {msg.get('k')}"
        )
        print(f"  PASS  sent frame: {msg}")
    finally:
        await mgr.shutdown()


async def test_unsubscribe_sends_message(user_id, ws_token, inst_token):
    """unsubscribe_touchline sends the correct 't':'u' frame to Shoonya."""
    print(f"\n--- Unsubscribe message test (token={inst_token}) ---")
    mgr = _make_manager(user_id, ws_token)
    sent_messages: list = []

    try:
        await mgr._connect_shoonya()

        original_send = mgr._shoonya_ws.send
        async def recording_send(msg):
            sent_messages.append(json.loads(msg))
            return await original_send(msg)
        mgr._shoonya_ws.send = recording_send

        tokens = [{"exch": "NSE", "token": inst_token}]
        await mgr.subscribe_touchline(tokens)
        await mgr.unsubscribe_touchline(tokens)

        unsub = next((m for m in reversed(sent_messages) if m.get("t") == "u"), None)
        assert unsub is not None, f"No unsubscribe frame found in: {sent_messages}"
        assert f"NSE|{inst_token}" in unsub.get("k", ""), (
            f"Expected 'NSE|{inst_token}' in unsubscribe k field, got: {unsub}"
        )
        print(f"  PASS  unsubscribe frame: {unsub}")
    finally:
        await mgr.shutdown()


async def test_tick_fanout_to_client(user_id, ws_token, inst_token):
    """Ticks from Shoonya are fanned out to registered MockClient.
    Skips gracefully if no tick arrives within TICK_WAIT_SECONDS (market closed)."""
    print(f"\n--- Tick fan-out test (token={inst_token}, wait={TICK_WAIT_SECONDS}s) ---")
    mgr = _make_manager(user_id, ws_token)
    client = MockClient()

    try:
        await mgr.add_client(client)
        await mgr.subscribe_touchline([{"exch": "NSE", "token": inst_token}])

        deadline = asyncio.get_event_loop().time() + TICK_WAIT_SECONDS
        while asyncio.get_event_loop().time() < deadline:
            if client.messages:
                break
            await asyncio.sleep(0.2)

        if client.messages:
            tick = client.messages[0]
            print(f"  PASS  Received {len(client.messages)} tick(s)  first={tick}")
        else:
            print(f"  SKIP  No tick in {TICK_WAIT_SECONDS}s — market may be closed (not a failure)")
    finally:
        await mgr.shutdown()


async def test_dead_client_pruned(user_id, ws_token, inst_token):
    """A client that raises on send_json is removed from _clients automatically."""
    print(f"\n--- Dead client pruning test ---")
    mgr = _make_manager(user_id, ws_token)
    dead_client = MockClient()
    dead_client._fail = True
    live_client = MockClient()

    try:
        await mgr._connect_shoonya()
        mgr._clients.add(dead_client)
        mgr._clients.add(live_client)

        # Simulate a broadcast — dead_client will raise, live_client will receive
        await mgr._broadcast({"t": "tf", "tk": inst_token, "lp": "100"})

        assert dead_client not in mgr._clients, "Dead client was not pruned from _clients"
        assert live_client in mgr._clients, "Live client was wrongly removed"
        assert len(live_client.messages) == 1, f"Expected 1 message on live client, got {len(live_client.messages)}"
        print(f"  PASS  Dead client pruned  live_client messages={live_client.messages}")
    finally:
        await mgr.shutdown()


async def test_shutdown_clears_state(user_id, ws_token):
    """shutdown() leaves the manager in a clean idle state."""
    print("\n--- Shutdown state test ---")
    mgr = _make_manager(user_id, ws_token)
    client = MockClient()
    await mgr.add_client(client)
    assert mgr.connected

    await mgr.shutdown()
    assert not mgr.connected,         "connected should be False after shutdown"
    assert mgr._shoonya_ws is None,   "_shoonya_ws should be None after shutdown"
    assert mgr._listener_task is None,"_listener_task should be None after shutdown"
    assert len(mgr._clients) == 0,    "_clients should be empty after shutdown"
    print(f"  PASS  All state cleared after shutdown")


# ── Main ───────────────────────────────────────────────────────────────────────

async def main():
    print("=== ShoonyaWSManager Test Suite ===")
    print("Authenticating...")
    user_id, token = _authenticate()
    print(f"Authenticated as user_id={user_id!r}  token_prefix={token[:10]!r}")

    inst_token = _get_token(user_id, token, "RELIANCE", "NSE")
    print(f"Discovered RELIANCE token={inst_token!r}")

    await test_connect_and_auth(user_id, token)
    await test_add_remove_client(user_id, token)
    await test_subscribe_touchline_sends_message(user_id, token, inst_token)
    await test_unsubscribe_sends_message(user_id, token, inst_token)
    await test_dead_client_pruned(user_id, token, inst_token)
    await test_shutdown_clears_state(user_id, token)
    await test_tick_fanout_to_client(user_id, token, inst_token)  # last — waits for ticks

    print("\n=== All tests completed ===")


if __name__ == "__main__":
    asyncio.run(main())
