"""Tests for scripmaster.py — NFO scripmaster download, parse and lookup functions.

Run standalone:  python tests/test_scripmaster.py
"""

import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripmaster import get_nfo_df, get_expiries, build_token_map


def test_download_and_parse():
    print("test_download_and_parse ... ", end="", flush=True)
    df = get_nfo_df()
    assert df is not None, "DataFrame is None"
    assert not df.empty, "DataFrame is empty"

    required = {"token", "symbol", "tsym", "instrument", "option_type", "strike", "expiry"}
    missing = required - set(df.columns)
    assert not missing, f"Missing columns: {missing}"

    assert len(df) > 1000, f"Expected >1000 rows, got {len(df)}"
    assert df["option_type"].str.upper().isin(["CE", "PE"]).all(), \
        "Unexpected option_type values: " + str(df["option_type"].unique())

    print(f"OK ({len(df)} rows)")


def test_get_expiries_sorted():
    print("test_get_expiries_sorted ... ", end="", flush=True)
    df = get_nfo_df()

    for sym in ("NIFTY", "BANKNIFTY"):
        expiries = get_expiries(sym, df)
        assert isinstance(expiries, list), f"{sym}: expected list"
        assert len(expiries) > 0, f"{sym}: no expiries found"

        # Verify sorted ascending
        parsed = [datetime.strptime(e.title(), "%d-%b-%Y") for e in expiries]
        assert parsed == sorted(parsed), f"{sym}: expiries not sorted — {expiries}"

    assert get_expiries("XYZFAKE999", df) == [], "Expected [] for unknown symbol"
    print("OK")


def test_build_token_map_structure():
    print("test_build_token_map_structure ... ", end="", flush=True)
    df = get_nfo_df()
    expiries = get_expiries("NIFTY", df)
    assert expiries, "No expiries for NIFTY"

    token_map, strike_map = build_token_map("NIFTY", expiries[0], df)
    assert token_map, "token_map is empty"
    assert strike_map, "strike_map is empty"

    required_fields = {"token", "tsym", "exch", "strike", "opttype", "expiry"}
    for key, val in token_map.items():
        assert re.match(r"^NFO\|\d+$", key), f"Bad token_map key format: {key}"
        missing = required_fields - set(val.keys())
        assert not missing, f"token_map entry missing fields: {missing}"
        assert val["exch"] == "NFO", f"exch should be NFO, got {val['exch']}"
        assert val["opttype"] in ("CE", "PE"), f"Unexpected opttype: {val['opttype']}"

    print(f"OK ({len(token_map)} tokens, {len(strike_map)} strikes)")


def test_token_format_is_nfo_pipe():
    print("test_token_format_is_nfo_pipe ... ", end="", flush=True)
    df = get_nfo_df()
    expiries = get_expiries("BANKNIFTY", df)
    assert expiries, "No expiries for BANKNIFTY"

    token_map, _ = build_token_map("BANKNIFTY", expiries[0], df)
    assert token_map, "token_map is empty"

    for key, val in list(token_map.items())[:5]:
        bare = key.split("|", 1)[1]
        assert bare == val["token"], \
            f"Key token '{bare}' doesn't match val token '{val['token']}'"
        assert bare.isdigit(), f"Token should be numeric, got: {bare}"

    print("OK")


def test_strike_map_has_ce_and_pe():
    print("test_strike_map_has_ce_and_pe ... ", end="", flush=True)
    df = get_nfo_df()
    expiries = get_expiries("NIFTY", df)
    assert expiries

    _, strike_map = build_token_map("NIFTY", expiries[0], df)
    both = [s for s, v in strike_map.items() if "CE" in v and "PE" in v]
    assert len(both) > 0, "No strikes have both CE and PE"

    for strike in both[:5]:
        ce_tok = strike_map[strike]["CE"]
        pe_tok = strike_map[strike]["PE"]
        assert ce_tok != pe_tok, f"CE and PE tokens identical for strike {strike}"

    print(f"OK ({len(both)} strikes with both CE+PE)")


def test_unknown_expiry_returns_empty():
    print("test_unknown_expiry_returns_empty ... ", end="", flush=True)
    df = get_nfo_df()
    token_map, strike_map = build_token_map("NIFTY", "01-JAN-1999", df)
    assert token_map == {}, f"Expected empty token_map, got {len(token_map)} entries"
    assert strike_map == {}, f"Expected empty strike_map, got {len(strike_map)} entries"
    print("OK")


def main():
    print("=== Scripmaster Test Suite ===\n")
    test_download_and_parse()
    test_get_expiries_sorted()
    test_build_token_map_structure()
    test_token_format_is_nfo_pipe()
    test_strike_map_has_ce_and_pe()
    test_unknown_expiry_returns_empty()
    print("\n=== All scripmaster tests passed. ===")


if __name__ == "__main__":
    main()
