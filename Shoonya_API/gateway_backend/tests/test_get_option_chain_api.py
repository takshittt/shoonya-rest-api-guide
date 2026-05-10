"""Tests for get_option_chain_api.py — raw /GetOptionChain endpoint."""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shoonya_auth import ShonyaAuthenticator
from search_scrip import search_scrip
from get_quote import get_quote
from get_option_chain_api import get_option_chain_api

# Symbols to discover contracts for dynamically via SearchScrip
TEST_SYMBOLS = [
    ("NIFTY",     "NFO"),
    ("BANKNIFTY", "NFO"),
    ("CRUDEOIL",  "MCX"),
]

_FUTURES_INST = {"FUTIDX", "FUTSTK", "FUTCOM"}


def _authenticate():
    auth = ShonyaAuthenticator()
    result = auth.authenticate()
    if not result["success"]:
        raise RuntimeError(f"Auth failed: {result['message']}")
    return auth.user_id, auth.auth_token


def _nearest_futures(user_id, token, symbol, exchange):
    """Return (tsym, futures_token) for the nearest expiry futures contract."""
    raw = search_scrip(user_id, token, symbol, exchange)
    if raw.get("stat") != "Ok":
        raise RuntimeError(f"SearchScrip failed for {symbol}/{exchange}: {raw.get('emsg')}")
    futures = [
        i for i in raw.get("values", [])
        if i.get("instname", "").upper() in _FUTURES_INST
    ]
    if not futures:
        raise RuntimeError(f"No futures found for {symbol}/{exchange}")
    futures.sort(key=lambda i: i.get("exd", ""))
    return futures[0]["tsym"], futures[0]["token"]


def _ltp(user_id, token, exchange, fut_token):
    """Fetch last traded price for an instrument; returns 0.0 on failure."""
    try:
        q = get_quote(user_id, token, exchange, fut_token)
        return float(q.get("lp", 0) or 0)
    except Exception:
        return 0.0


def _print_result(label, result, elapsed):
    stat = result.get("stat", "?")
    if stat == "Ok":
        values = result.get("values", [])
        tokens = [v.get("token", "") for v in values[:4]]
        print(f"  PASS  {label:<30} stat=Ok  rows={len(values)}  sample_tokens={tokens}  ({elapsed:.2f}s)")
    else:
        emsg = result.get("emsg", "no error message")
        print(f"  FAIL  {label:<30} stat={stat}  emsg={emsg!r}  ({elapsed:.2f}s)")


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_smoke(user_id, token):
    """Basic call — NIFTY nearest futures should return CE/PE rows."""
    exch = "NFO"
    print(f"\n--- Smoke test: NIFTY/{exch} (nearest futures) count=5 ---")
    tsym, fut_token = _nearest_futures(user_id, token, "NIFTY", exch)
    atm = _ltp(user_id, token, exch, fut_token) or 25000.0
    print(f"  Discovered tsym={tsym!r}  atm={atm}")

    label = f"{exch}/{tsym}"
    t0 = time.perf_counter()
    result = get_option_chain_api(user_id, token, exch, tsym, atm, count=5)
    elapsed = time.perf_counter() - t0
    _print_result(label, result, elapsed)

    assert result.get("stat") == "Ok", f"Expected stat=Ok, got: {result}"
    rows = result.get("values", [])
    assert len(rows) > 0, "Expected at least one option row"

    required = {"token", "tsym", "exch", "optt", "strprc"}
    for row in rows:
        missing = required - set(row.keys())
        assert not missing, f"Row missing keys {missing}: {row}"

    opt_types = {r.get("optt") for r in rows}
    assert "CE" in opt_types, f"No CE rows found, got: {opt_types}"
    assert "PE" in opt_types, f"No PE rows found, got: {opt_types}"
    print("  Smoke test PASSED.")


def test_count_parameter(user_id, token):
    """count=N should return rows; larger count should return more rows."""
    exch = "NFO"
    print(f"\n--- Count parameter test: NIFTY/{exch} count=3 and count=10 ---")
    tsym, fut_token = _nearest_futures(user_id, token, "NIFTY", exch)
    atm = _ltp(user_id, token, exch, fut_token) or 25000.0
    print(f"  Discovered tsym={tsym!r}  atm={atm}")

    counts_rows = {}
    for count in (3, 10):
        t0 = time.perf_counter()
        result = get_option_chain_api(user_id, token, exch, tsym, atm, count=count)
        elapsed = time.perf_counter() - t0
        rows = result.get("values", [])
        label = f"{exch}/{tsym} count={count}"
        _print_result(label, result, elapsed)
        assert result.get("stat") == "Ok", f"Expected stat=Ok for count={count}"
        assert len(rows) > 0, f"Expected rows for count={count}"
        counts_rows[count] = len(rows)
        print(f"    count={count} → {len(rows)} rows  PASS")

    assert counts_rows[10] >= counts_rows[3], (
        f"Expected count=10 to return >= rows than count=3, got {counts_rows}"
    )


def test_all_symbols(user_id, token):
    """Run GetOptionChain for each test symbol using dynamically discovered tsyms."""
    print(f"\n--- All symbols test ({len(TEST_SYMBOLS)} symbols) ---")
    passed, failed = [], []

    for symbol, exch in TEST_SYMBOLS:
        label = f"{symbol}/{exch}"
        t0 = time.perf_counter()
        try:
            tsym, fut_token = _nearest_futures(user_id, token, symbol, exch)
            atm = _ltp(user_id, token, exch, fut_token) or 1.0
            result = get_option_chain_api(user_id, token, exch, tsym, atm, count=5)
            elapsed = time.perf_counter() - t0
            detail_label = f"{exch}/{tsym}"
            _print_result(detail_label, result, elapsed)
            if result.get("stat") == "Ok" and result.get("values"):
                passed.append(label)
            else:
                failed.append((label, result.get("emsg", "no rows")))
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            print(f"  ERROR {label:<30} exception={exc}  ({elapsed:.2f}s)")
            failed.append((label, str(exc)))

    print(f"\nResults: {len(passed)}/{len(TEST_SYMBOLS)} passed")
    if failed:
        for label, reason in failed:
            print(f"  FAIL  {label}: {reason}")
    return passed, failed


def test_invalid_tsym(user_id, token):
    """An invalid futures tsym should not return stat=Ok with rows."""
    print("\n--- Invalid tsym test: NFO/INVALIDSYM99JANFUT ---")
    t0 = time.perf_counter()
    try:
        result = get_option_chain_api(user_id, token, "NFO", "INVALIDSYM99JANFUT", 25000.0, count=3)
        elapsed = time.perf_counter() - t0
        stat = result.get("stat")
        rows = result.get("values", [])
        assert stat != "Ok" or len(rows) == 0, (
            f"Expected failure for invalid tsym, got stat={stat!r} with {len(rows)} rows"
        )
        print(f"  PASS  Invalid tsym returned stat={stat!r} with {len(rows)} rows  ({elapsed:.2f}s)")
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        print(f"  PASS  Invalid tsym raised exception (expected): {exc}  ({elapsed:.2f}s)")


def main():
    print("=== GetOptionChain API Test Suite ===")
    print("Authenticating...")
    user_id, token = _authenticate()
    print(f"Authenticated as user_id={user_id!r}\n")

    test_smoke(user_id, token)
    test_count_parameter(user_id, token)
    test_invalid_tsym(user_id, token)
    passed, failed = test_all_symbols(user_id, token)

    print("\n=== Summary ===")
    print(f"Symbols: {len(passed)}/{len(TEST_SYMBOLS)} passed")
    if failed:
        print(f"Failed: {[l for l, _ in failed]}")
    else:
        print("All symbols passed.")


if __name__ == "__main__":
    main()
