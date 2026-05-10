"""Tests for option_chain.py — full pipeline: SearchScrip → ATM → GetOptionChain → GetQuotes."""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shoonya_auth import ShonyaAuthenticator
from option_chain import get_option_chain

# (symbol, exchange) pairs covering equity indices and a commodity
TEST_SYMBOLS = [
    ("NIFTY",     "NFO"),
    ("BANKNIFTY", "NFO"),
    ("CRUDEOIL",  "MCX"),
]


def _authenticate():
    auth = ShonyaAuthenticator()
    result = auth.authenticate()
    if not result["success"]:
        raise RuntimeError(f"Auth failed: {result['message']}")
    return auth.user_id, auth.auth_token


def _assert_chain_structure(result, label):
    """Assert the top-level shape of a successful get_option_chain response."""
    assert "error" not in result, f"{label}: got error: {result['error']}"
    assert "symbol"   in result, f"{label}: missing 'symbol'"
    assert "exchange" in result, f"{label}: missing 'exchange'"
    assert "expiry"   in result, f"{label}: missing 'expiry'"
    assert "expiries" in result, f"{label}: missing 'expiries'"
    assert "chain"    in result, f"{label}: missing 'chain'"
    assert isinstance(result["expiries"], list), f"{label}: 'expiries' is not a list"
    assert isinstance(result["chain"],    list), f"{label}: 'chain' is not a list"


def _assert_chain_rows(chain, label):
    """Assert every row in the chain has the correct shape."""
    assert len(chain) > 0, f"{label}: chain is empty"
    for row in chain:
        assert "strike" in row, f"{label}: row missing 'strike': {row}"
        assert "CE"     in row, f"{label}: row missing 'CE': {row}"
        assert "PE"     in row, f"{label}: row missing 'PE': {row}"
        for side in ("CE", "PE"):
            leg = row[side]
            if leg is not None:
                assert "token" in leg, f"{label}: {side} leg missing 'token': {leg}"
                assert "tsym"  in leg, f"{label}: {side} leg missing 'tsym': {leg}"
                assert "exch"  in leg, f"{label}: {side} leg missing 'exch': {leg}"


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_smoke(user_id, token):
    """Full pipeline for NIFTY/NFO — assert structure and at least one CE+PE row."""
    symbol, exchange = "NIFTY", "NFO"
    print(f"\n--- Smoke test: {symbol} on {exchange} ---")
    t0 = time.perf_counter()
    result = get_option_chain(user_id, token, symbol, exchange, count=5)
    elapsed = time.perf_counter() - t0

    _assert_chain_structure(result, f"{symbol}/{exchange}")
    _assert_chain_rows(result["chain"], f"{symbol}/{exchange}")

    # At least one expiry must exist
    assert len(result["expiries"]) > 0, "Expected at least one expiry"

    # At least one row must have both CE and PE
    both_sides = [r for r in result["chain"] if r["CE"] and r["PE"]]
    assert len(both_sides) > 0, "Expected at least one row with both CE and PE legs"

    print(f"  PASS  symbol={result['symbol']}  exchange={result['exchange']}")
    print(f"        expiry={result['expiry']}  expiries={result['expiries']}")
    print(f"        chain rows={len(result['chain'])}  rows_with_both_legs={len(both_sides)}")
    print(f"        elapsed={elapsed:.2f}s")
    print("  Smoke test PASSED.")
    return result


def test_expiry_list(user_id, token):
    """expiries list must be sorted and each selected expiry must exist in it."""
    symbol, exchange = "BANKNIFTY", "NFO"
    print(f"\n--- Expiry list test: {symbol}/{exchange} ---")
    result = get_option_chain(user_id, token, symbol, exchange, count=3)
    _assert_chain_structure(result, f"{symbol}/{exchange}")

    expiries = result["expiries"]
    assert expiries == sorted(expiries), f"expiries not sorted: {expiries}"
    assert result["expiry"] in expiries, (
        f"selected expiry {result['expiry']!r} not in expiries list {expiries}"
    )
    print(f"  PASS  expiries={expiries}")
    print(f"        selected={result['expiry']!r}  (in list: True)")


def test_specific_expiry(user_id, token):
    """Passing an explicit expiry should select that expiry in the response."""
    symbol, exchange = "NIFTY", "NFO"
    print(f"\n--- Specific expiry test: {symbol}/{exchange} ---")

    # First call to discover available expiries
    base = get_option_chain(user_id, token, symbol, exchange, count=3)
    _assert_chain_structure(base, f"{symbol}/{exchange} base")
    expiries = base["expiries"]
    if len(expiries) < 2:
        print(f"  SKIP  Only {len(expiries)} expiry available, cannot test expiry selection.")
        return

    target_expiry = expiries[-1]  # pick last (furthest) expiry
    print(f"  Requesting expiry={target_expiry!r}")
    t0 = time.perf_counter()
    result = get_option_chain(user_id, token, symbol, exchange, expiry=target_expiry, count=3)
    elapsed = time.perf_counter() - t0
    _assert_chain_structure(result, f"{symbol}/{exchange} expiry={target_expiry}")

    assert result["expiry"] == target_expiry, (
        f"Expected expiry={target_expiry!r}, got {result['expiry']!r}"
    )
    print(f"  PASS  expiry={result['expiry']!r} correctly selected  ({elapsed:.2f}s)")


def test_all_symbols(user_id, token):
    """Run the full pipeline for each test symbol and report pass/fail."""
    print(f"\n--- All symbols test ({len(TEST_SYMBOLS)} symbols) ---")
    passed, failed = [], []

    for symbol, exchange in TEST_SYMBOLS:
        label = f"{symbol}/{exchange}"
        t0 = time.perf_counter()
        try:
            result = get_option_chain(user_id, token, symbol, exchange, count=5)
            elapsed = time.perf_counter() - t0
            if "error" in result:
                print(f"  FAIL  {label:<20} error={result['error']!r}  ({elapsed:.2f}s)")
                failed.append((label, result["error"]))
            elif not result.get("chain"):
                print(f"  FAIL  {label:<20} chain is empty  ({elapsed:.2f}s)")
                failed.append((label, "empty chain"))
            else:
                rows = len(result["chain"])
                both = sum(1 for r in result["chain"] if r["CE"] and r["PE"])
                print(f"  PASS  {label:<20} rows={rows}  both_legs={both}  expiry={result['expiry']}  ({elapsed:.2f}s)")
                passed.append(label)
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            print(f"  ERROR {label:<20} exception={exc}  ({elapsed:.2f}s)")
            failed.append((label, str(exc)))

    print(f"\nResults: {len(passed)}/{len(TEST_SYMBOLS)} passed")
    if failed:
        for label, reason in failed:
            print(f"  FAIL  {label}: {reason}")
    return passed, failed


def test_invalid_symbol(user_id, token):
    """An invalid symbol should return an error or empty chain — not crash."""
    print("\n--- Invalid symbol test: XYZFAKE999/NFO ---")
    t0 = time.perf_counter()
    result = get_option_chain(user_id, token, "XYZFAKE999", "NFO", count=5)
    elapsed = time.perf_counter() - t0
    chain = result.get("chain", [])
    err   = result.get("error")
    assert len(chain) == 0 or err, (
        f"Expected empty chain or error for invalid symbol, got {len(chain)} rows"
    )
    print(f"  PASS  error={err!r}  chain_len={len(chain)}  ({elapsed:.2f}s)")


def test_wrong_exchange(user_id, token):
    """NIFTY on MCX (wrong exchange) should return no chain rows."""
    print("\n--- Wrong exchange test: NIFTY on MCX ---")
    t0 = time.perf_counter()
    result = get_option_chain(user_id, token, "NIFTY", "MCX", count=5)
    elapsed = time.perf_counter() - t0
    chain = result.get("chain", [])
    expiries = result.get("expiries", [])
    assert len(chain) == 0, f"Expected empty chain for NIFTY/MCX, got {len(chain)} rows"
    print(f"  PASS  chain_len={len(chain)}  expiries={expiries}  ({elapsed:.2f}s)")


def test_ltp_in_legs(user_id, token):
    """At least some legs should have an lp (last price) field from GetQuotes."""
    symbol, exchange = "NIFTY", "NFO"
    print(f"\n--- LTP pre-fill test: {symbol}/{exchange} ---")
    result = get_option_chain(user_id, token, symbol, exchange, count=5)
    _assert_chain_structure(result, f"{symbol}/{exchange}")

    legs_with_lp = [
        leg
        for row in result["chain"]
        for leg in (row["CE"], row["PE"])
        if leg and leg.get("lp")
    ]
    print(f"  Legs with lp: {len(legs_with_lp)} / {len(result['chain']) * 2}")
    assert len(legs_with_lp) > 0, "Expected at least some legs to have lp from GetQuotes"
    print(f"  PASS  {len(legs_with_lp)} legs have live lp from GetQuotes")


def main():
    print("=== OptionChain Pipeline Test Suite ===")
    print("Authenticating...")
    user_id, token = _authenticate()
    print(f"Authenticated as user_id={user_id!r}")

    test_smoke(user_id, token)
    test_expiry_list(user_id, token)
    test_specific_expiry(user_id, token)
    test_invalid_symbol(user_id, token)
    test_wrong_exchange(user_id, token)
    test_ltp_in_legs(user_id, token)
    passed, failed = test_all_symbols(user_id, token)

    print("\n=== Summary ===")
    print(f"Symbols: {len(passed)}/{len(TEST_SYMBOLS)} passed")
    if failed:
        print(f"Failed: {[l for l, _ in failed]}")
    else:
        print("All symbols passed.")


if __name__ == "__main__":
    main()
