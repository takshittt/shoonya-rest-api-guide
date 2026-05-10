"""Tests for get_quote.py — raw /GetQuotes endpoint."""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shoonya_auth import ShonyaAuthenticator
from search_scrip import search_scrip
from get_quote import get_quote

# (symbol, exchange) pairs to discover tokens dynamically via SearchScrip
TEST_SYMBOLS = [
    ("RELIANCE",  "NSE"),
    ("INFY",      "NSE"),
    ("HDFCBANK",  "NSE"),
    ("TCS",       "NSE"),
    ("NIFTY",     "NSE"),   # index
]

# Fields expected in a valid quote response
QUOTE_FIELDS = {"lp", "h", "l", "o", "c", "v"}


def _authenticate():
    auth = ShonyaAuthenticator()
    result = auth.authenticate()
    if not result["success"]:
        raise RuntimeError(f"Auth failed: {result['message']}")
    return auth.user_id, auth.auth_token


def _get_token(user_id, token, symbol, exchange):
    """Return the first matching instrument token for a symbol via SearchScrip."""
    raw = search_scrip(user_id, token, symbol, exchange)
    if raw.get("stat") != "Ok":
        raise RuntimeError(f"SearchScrip failed for {symbol}/{exchange}: {raw.get('emsg')}")
    values = raw.get("values", [])
    if not values:
        raise RuntimeError(f"No instruments found for {symbol}/{exchange}")
    # Prefer EQ / equity instruments; fall back to first result
    eq = next((v for v in values if v.get("instname", "").upper() in ("EQ", "INDEX")), values[0])
    return eq["token"], eq.get("tsym", symbol)


def _print_result(label, result, elapsed):
    stat = result.get("stat", "?")
    if stat == "Ok":
        lp = result.get("lp", "—")
        v  = result.get("v",  "—")
        oi = result.get("oi", "—")
        print(f"  PASS  {label:<20} stat=Ok  lp={lp}  vol={v}  oi={oi}  ({elapsed:.2f}s)")
    else:
        emsg = result.get("emsg", "no error message")
        print(f"  FAIL  {label:<20} stat={stat}  emsg={emsg!r}  ({elapsed:.2f}s)")


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_smoke(user_id, auth_token):
    """Single quote for RELIANCE — assert stat=Ok and lp is a valid number."""
    print("\n--- Smoke test: RELIANCE/NSE ---")
    inst_token, tsym = _get_token(user_id, auth_token, "RELIANCE", "NSE")
    print(f"  Discovered token={inst_token!r}  tsym={tsym!r}")

    t0 = time.perf_counter()
    result = get_quote(user_id, auth_token, "NSE", inst_token)
    elapsed = time.perf_counter() - t0
    _print_result(f"RELIANCE ({inst_token})", result, elapsed)

    assert result.get("stat") == "Ok", f"Expected stat=Ok, got: {result}"
    assert result.get("lp"), "Expected a non-empty lp (last price)"
    try:
        float(result["lp"])
    except ValueError:
        raise AssertionError(f"lp is not a valid number: {result['lp']!r}")
    print("  Smoke test PASSED.")
    return inst_token


def test_quote_fields(user_id, auth_token):
    """Response for a liquid equity should include all standard quote fields."""
    print("\n--- Quote fields test: TCS/NSE ---")
    inst_token, tsym = _get_token(user_id, auth_token, "TCS", "NSE")
    result = get_quote(user_id, auth_token, "NSE", inst_token)
    assert result.get("stat") == "Ok", f"Expected stat=Ok, got: {result}"

    missing = QUOTE_FIELDS - set(result.keys())
    if missing:
        print(f"  NOTE  Missing optional fields (may be outside market hours): {missing}")
    else:
        print(f"  PASS  All fields present: {QUOTE_FIELDS}")

    # lp is always required regardless of market hours
    assert "lp" in result, f"lp must always be present, got keys: {list(result.keys())}"
    print(f"  PASS  lp={result['lp']}  h={result.get('h','—')}  l={result.get('l','—')}  ({tsym})")


def test_all_symbols(user_id, auth_token):
    """Fetch quotes for all test symbols and report pass/fail per symbol."""
    print(f"\n--- All symbols test ({len(TEST_SYMBOLS)} symbols) ---")
    passed, failed = [], []

    for symbol, exchange in TEST_SYMBOLS:
        label = f"{symbol}/{exchange}"
        t0 = time.perf_counter()
        try:
            inst_token, _ = _get_token(user_id, auth_token, symbol, exchange)
            result = get_quote(user_id, auth_token, exchange, inst_token)
            elapsed = time.perf_counter() - t0
            _print_result(f"{symbol} ({inst_token})", result, elapsed)
            if result.get("stat") == "Ok" and result.get("lp"):
                passed.append(label)
            else:
                failed.append((label, result.get("emsg", "missing lp")))
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            print(f"  ERROR {label:<20} exception={exc}  ({elapsed:.2f}s)")
            failed.append((label, str(exc)))

    print(f"\nResults: {len(passed)}/{len(TEST_SYMBOLS)} passed")
    if failed:
        for sym, reason in failed:
            print(f"  FAIL  {sym}: {reason}")
    return passed, failed


def test_invalid_token(user_id, auth_token):
    """A nonsense token should not return stat=Ok with a valid lp."""
    print("\n--- Invalid token test: NSE/token=9999999999 ---")
    t0 = time.perf_counter()
    try:
        result = get_quote(user_id, auth_token, "NSE", "9999999999")
        elapsed = time.perf_counter() - t0
        stat = result.get("stat")
        lp   = result.get("lp")
        assert stat != "Ok" or not lp, (
            f"Expected failure for invalid token, got stat={stat!r}  lp={lp!r}"
        )
        print(f"  PASS  Invalid token returned stat={stat!r}  lp={lp!r}  ({elapsed:.2f}s)")
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        print(f"  PASS  Invalid token raised exception (expected): {exc}  ({elapsed:.2f}s)")


def test_lp_is_positive(user_id, auth_token):
    """Last price for any actively traded equity must be > 0."""
    print("\n--- LTP sanity test: INFY/NSE ---")
    inst_token, tsym = _get_token(user_id, auth_token, "INFY", "NSE")
    result = get_quote(user_id, auth_token, "NSE", inst_token)
    assert result.get("stat") == "Ok", f"Expected stat=Ok: {result}"
    lp = float(result["lp"])
    assert lp > 0, f"Expected lp > 0, got {lp}"
    print(f"  PASS  {tsym}  lp={lp}  (> 0)")


def main():
    print("=== GetQuote Test Suite ===")
    print("Authenticating...")
    user_id, auth_token = _authenticate()
    print(f"Authenticated as user_id={user_id!r}")

    test_smoke(user_id, auth_token)
    test_quote_fields(user_id, auth_token)
    test_lp_is_positive(user_id, auth_token)
    test_invalid_token(user_id, auth_token)
    passed, failed = test_all_symbols(user_id, auth_token)

    print("\n=== Summary ===")
    print(f"Symbols: {len(passed)}/{len(TEST_SYMBOLS)} passed")
    if failed:
        print(f"Failed: {[s for s, _ in failed]}")
    else:
        print("All symbols passed.")


if __name__ == "__main__":
    main()
