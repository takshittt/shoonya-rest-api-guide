"""Tests for search_scrip.py — uses real Shoonya API with cached auth token."""

import sys
import os
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shoonya_auth import ShonyaAuthenticator
from search_scrip import search_scrip

NIFTY50_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "TITAN",
    "SUNPHARMA", "ULTRACEMCO", "BAJFINANCE", "WIPRO", "NESTLEIND",
    "HCLTECH", "POWERGRID", "NTPC", "TECHM", "ONGC",
    "TATAMOTORS", "TATASTEEL", "JSWSTEEL", "ADANIENT", "ADANIPORTS",
    "COALINDIA", "GRASIM", "HDFCLIFE", "INDUSINDBK", "CIPLA",
    "DRREDDY", "DIVISLAB", "EICHERMOT", "BPCL", "BAJAJ-AUTO",
    "BAJAJFINSV", "BRITANNIA", "APOLLOHOSP", "SBILIFE", "HEROMOTOCO",
    "TATACONSUM", "HINDALCO", "UPL", "M&M", "LTM",
]

EXCHANGE = "NSE"


def _authenticate():
    auth = ShonyaAuthenticator()
    result = auth.authenticate()
    if not result["success"]:
        raise RuntimeError(f"Auth failed: {result['message']}")
    return auth.user_id, auth.auth_token


def _print_result(symbol, result, elapsed):
    stat = result.get("stat", "?")
    if stat == "Ok":
        values = result.get("values", [])
        tokens = [v.get("token", "") for v in values[:3]]
        print(f"  PASS  {symbol:<15} stat=Ok  hits={len(values)}  tokens={tokens}  ({elapsed:.2f}s)")
    else:
        emsg = result.get("emsg", "no error message")
        print(f"  FAIL  {symbol:<15} stat={stat}  emsg={emsg!r}  ({elapsed:.2f}s)")


def test_single_symbol(user_id, token, symbol="RELIANCE", exchange=EXCHANGE):
    """Smoke test: search for one symbol."""
    print(f"\n--- Single symbol test: {symbol} on {exchange} ---")
    t0 = time.perf_counter()
    result = search_scrip(user_id, token, symbol, exchange)
    elapsed = time.perf_counter() - t0
    _print_result(symbol, result, elapsed)
    assert result.get("stat") == "Ok", f"Expected stat=Ok, got: {result}"
    assert len(result.get("values", [])) > 0, "Expected at least one result"
    print("  Smoke test PASSED.")
    return result


def test_no_exchange(user_id, token, symbol="INFY"):
    """Search without specifying an exchange — should still return results."""
    print(f"\n--- No-exchange test: {symbol} ---")
    t0 = time.perf_counter()
    result = search_scrip(user_id, token, symbol)
    elapsed = time.perf_counter() - t0
    _print_result(symbol, result, elapsed)
    assert result.get("stat") == "Ok", f"Expected stat=Ok, got: {result}"
    print("  No-exchange test PASSED.")


def test_all_nifty50(user_id, token):
    """Search every Nifty 50 symbol and report pass/fail for each."""
    print(f"\n--- Nifty 50 bulk search ({len(NIFTY50_SYMBOLS)} symbols, exchange={EXCHANGE}) ---")
    passed = []
    failed = []

    for symbol in NIFTY50_SYMBOLS:
        t0 = time.perf_counter()
        try:
            result = search_scrip(user_id, token, symbol, EXCHANGE)
            elapsed = time.perf_counter() - t0
            _print_result(symbol, result, elapsed)
            if result.get("stat") == "Ok" and result.get("values"):
                passed.append(symbol)
            else:
                failed.append((symbol, result.get("emsg", "no results")))
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            print(f"  ERROR {symbol:<15} exception={exc}  ({elapsed:.2f}s)")
            failed.append((symbol, str(exc)))

    print(f"\nResults: {len(passed)}/{len(NIFTY50_SYMBOLS)} passed")
    if failed:
        print("Failed symbols:")
        for sym, reason in failed:
            print(f"  {sym}: {reason}")
    return passed, failed


def test_invalid_symbol(user_id, token):
    """Searching a nonsense symbol should return stat != Ok with no values."""
    print("\n--- Invalid symbol test: XYZINVALID999 ---")
    result = search_scrip(user_id, token, "XYZINVALID999", EXCHANGE)
    stat = result.get("stat")
    values = result.get("values", [])
    assert stat != "Ok" or len(values) == 0, (
        f"Expected no results for invalid symbol, got stat={stat!r} with {len(values)} hits"
    )
    print(f"  PASS  Invalid symbol correctly returned stat={stat!r} with {len(values)} results.")


def main():
    print("=== SearchScrip Test Suite ===")
    print("Authenticating...")
    user_id, token = _authenticate()
    print(f"Authenticated as user_id={user_id!r}")

    test_single_symbol(user_id, token)
    test_no_exchange(user_id, token)
    test_invalid_symbol(user_id, token)
    passed, failed = test_all_nifty50(user_id, token)

    print("\n=== Summary ===")
    print(f"Nifty 50 bulk: {len(passed)}/{len(NIFTY50_SYMBOLS)} passed")
    if failed:
        print(f"Failed ({len(failed)}): {[s for s, _ in failed]}")
    else:
        print("All Nifty 50 symbols found successfully.")


if __name__ == "__main__":
    main()
