"""Option chain builder — scripmaster-first with REST fallback.

Primary flow (NFO):
  1. Download/cached scripmaster → filter by symbol + expiry → token_map + strike_map
  2. GetQuotes on underlying spot token → ATM strike
  3. Slice count strikes around ATM
  4. Parallel GetQuotes for initial price snapshot
  5. Return structured chain for the frontend table

Fallback flow (non-NFO or scripmaster failure):
  Same as the original: SearchScrip → GetOptionChain API → parallel GetQuotes
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from search_scrip import search_scrip
from get_quote import get_quote
from get_option_chain_api import get_option_chain_api
from scripmaster import get_nfo_df, get_expiries, build_token_map

log = logging.getLogger(__name__)


def _fetch_quote(user_id: str, auth_token: str, exch: str, token: str) -> Dict:
    """Fetch a single quote; returns empty dict on any error."""
    try:
        data = get_quote(user_id, auth_token, exch, token)
        if data.get("stat") == "Ok":
            return {
                **{k: data.get(k, "") for k in ("lp", "oi", "h", "l", "o", "c")},
                "v": data.get("v") or "0",  # Shoonya omits v when zero; default to "0"
            }
    except Exception:
        pass
    return {}


def _parallel_quotes(
    user_id: str,
    auth_token: str,
    tokens: List[tuple],  # [(strike, opt_type, exch, token), ...]
) -> Dict[str, Dict]:
    """Fetch quotes in parallel; returns {token: quote_dict}."""
    quotes: Dict[str, Dict] = {}
    if not tokens:
        return quotes
    with ThreadPoolExecutor(max_workers=min(len(tokens), 20)) as pool:
        future_map = {
            pool.submit(_fetch_quote, user_id, auth_token, exch, token): token
            for _, _, exch, token in tokens
        }
        for fut in as_completed(future_map):
            quotes[future_map[fut]] = fut.result()
    return quotes


def build_chain_from_scripmaster(
    user_id: str,
    auth_token: str,
    symbol: str,
    exchange: str,
    expiry: Optional[str],
    underlying_token: Optional[str],
    strikeprice: Optional[float],
    count: int,
) -> Dict[str, Any]:
    """Build option chain using the downloaded NFO scripmaster."""
    df = get_nfo_df()

    all_expiries = get_expiries(symbol, df)
    if not all_expiries:
        return {"symbol": symbol, "exchange": exchange, "expiries": [], "chain": []}

    # Resolve requested expiry
    if expiry and expiry in all_expiries:
        selected_expiry = expiry
    else:
        selected_expiry = all_expiries[0]

    token_map, strike_map = build_token_map(symbol, selected_expiry, df)
    if not strike_map:
        return {
            "symbol": symbol, "exchange": exchange,
            "expiry": selected_expiry, "expiries": all_expiries, "chain": [],
        }

    # Determine ATM
    atm: float = 0.0
    if strikeprice is not None:
        atm = float(strikeprice)
    elif underlying_token:
        try:
            q = get_quote(user_id, auth_token, exchange, underlying_token)
            lp = q.get("lp", "")
            if lp:
                atm = float(lp)
        except Exception:
            pass

    sorted_strikes = sorted(strike_map.keys())
    if atm > 0:
        atm_strike = min(sorted_strikes, key=lambda s: abs(s - atm))
    else:
        atm_strike = sorted_strikes[len(sorted_strikes) // 2]

    atm_idx = sorted_strikes.index(atm_strike)
    lo = max(0, atm_idx - count)
    hi = min(len(sorted_strikes), atm_idx + count + 1)
    filtered_strikes = sorted_strikes[lo:hi]

    # Collect all tokens for the slice
    all_tokens = [
        (strike, opt_type, "NFO", strike_map[strike][opt_type])
        for strike in filtered_strikes
        for opt_type in ("CE", "PE")
        if opt_type in strike_map.get(strike, {})
    ]

    quotes = _parallel_quotes(user_id, auth_token, all_tokens)

    # Assemble chain rows
    chain = []
    for strike in filtered_strikes:
        row: Dict[str, Any] = {"strike": strike}
        for opt_type in ("CE", "PE"):
            token = strike_map[strike].get(opt_type)
            if token:
                inst = token_map[f"NFO|{token}"]
                row[opt_type] = {
                    "token": inst["token"],
                    "tsym":  inst["tsym"],
                    "exch":  "NFO",
                    **quotes.get(token, {}),
                }
            else:
                row[opt_type] = None
        chain.append(row)

    return {
        "symbol":   symbol,
        "exchange": exchange,
        "expiry":   selected_expiry,
        "expiries": all_expiries,
        "chain":    chain,
    }


def _futures_tsym(instruments: List[Dict], symbol: str, expiry: Optional[str]) -> Optional[Dict]:
    """Find the futures contract for the requested expiry from SearchScrip results."""
    futures = [
        i for i in instruments
        if i.get("instname", "").upper() in ("FUTIDX", "FUTSTK", "FUTCOM")
        and i.get("sym", "").upper() == symbol.upper()
    ]
    if not futures:
        return None
    if expiry:
        match = [f for f in futures if f.get("exd") == expiry]
        if match:
            return match[0]
    return futures[0]


def get_option_chain(
    user_id: str,
    auth_token: str,
    symbol: str,
    exchange: str,
    expiry: Optional[str] = None,
    underlying_token: Optional[str] = None,
    strikeprice: Optional[float] = None,
    count: int = 15,
) -> Dict[str, Any]:
    """
    Build a structured option chain for a symbol.

    For NFO, tries the scripmaster path first (faster, no extra API calls).
    Falls back to the REST GetOptionChain API path on any failure.

    Returns:
      {
        "symbol": "BANKNIFTY",
        "exchange": "NFO",
        "expiry": "26-Jun-2025",
        "expiries": ["26-Jun-2025", "31-Jul-2025"],
        "chain": [
          {
            "strike": 50000,
            "CE": {"token": "...", "tsym": "...", "exch": "NFO",
                   "lp": "120.50", "oi": "5000", "v": "1000"},
            "PE": {"token": "...", "tsym": "...", "exch": "NFO",
                   "lp": "80.30",  "oi": "3000", "v": "800"}
          },
          ...
        ]
      }
    """
    # --- Primary: scripmaster path (NFO only) ---
    if exchange.upper() == "NFO":
        try:
            result = build_chain_from_scripmaster(
                user_id, auth_token, symbol, exchange,
                expiry, underlying_token, strikeprice, count,
            )
            if result.get("chain") is not None:
                log.debug("option chain built via scripmaster for %s", symbol)
                return result
        except Exception as exc:
            log.warning("scripmaster path failed (%s) — falling back to REST", exc)

    # --- Fallback: REST SearchScrip + GetOptionChain API ---
    raw = search_scrip(user_id, auth_token, symbol, exchange)
    if raw.get("stat") != "Ok":
        return {"error": raw.get("emsg", "Search failed"), "chain": []}

    instruments: List[Dict] = raw.get("values", [])

    futures_list = [
        i for i in instruments
        if i.get("instname", "").upper() in ("FUTIDX", "FUTSTK", "FUTCOM")
        and i.get("sym", "").upper() == symbol.upper()
    ]
    all_expiries = sorted(set(f["exd"] for f in futures_list if f.get("exd")))

    if not all_expiries:
        return {"symbol": symbol, "exchange": exchange, "expiries": [], "chain": []}

    fut = _futures_tsym(instruments, symbol, expiry)
    if not fut:
        return {"symbol": symbol, "exchange": exchange, "expiries": all_expiries, "chain": []}

    selected_expiry = fut.get("exd", all_expiries[0])
    futures_tsym = fut.get("tsym", "")

    atm = strikeprice
    if atm is None:
        ltp_token = underlying_token or fut.get("token", "")
        if ltp_token:
            try:
                q = get_quote(user_id, auth_token, exchange, ltp_token)
                ltp_str = q.get("lp", "")
                if ltp_str:
                    atm = float(ltp_str)
            except Exception:
                pass
    if atm is None:
        atm = 0.0

    chain_raw = get_option_chain_api(user_id, auth_token, exchange, futures_tsym, atm, count)
    if chain_raw.get("stat") != "Ok":
        return {
            "error": chain_raw.get("emsg", "GetOptionChain failed"),
            "symbol": symbol, "exchange": exchange,
            "expiry": selected_expiry, "expiries": all_expiries, "chain": [],
        }

    option_instruments: List[Dict] = chain_raw.get("values", [])

    strikes_map: Dict[float, Dict[str, Dict]] = {}
    for inst in option_instruments:
        opt_type = inst.get("optt", "")
        if opt_type not in ("CE", "PE"):
            continue
        try:
            strike = float(inst.get("strprc", 0))
        except (ValueError, TypeError):
            continue
        strikes_map.setdefault(strike, {})[opt_type] = {
            "token": inst.get("token", ""),
            "tsym":  inst.get("tsym", ""),
            "exch":  inst.get("exch", exchange),
        }

    sorted_strikes = sorted(strikes_map.keys())

    all_tokens = [
        (strike, opt_type, strikes_map[strike][opt_type]["exch"], strikes_map[strike][opt_type]["token"])
        for strike in sorted_strikes
        for opt_type in ("CE", "PE")
        if opt_type in strikes_map[strike]
    ]

    quotes = _parallel_quotes(user_id, auth_token, all_tokens)

    chain = []
    for strike in sorted_strikes:
        row: Dict[str, Any] = {"strike": strike}
        for opt_type in ("CE", "PE"):
            inst_data = strikes_map[strike].get(opt_type)
            if inst_data:
                row[opt_type] = {**inst_data, **quotes.get(inst_data["token"], {})}
            else:
                row[opt_type] = None
        chain.append(row)

    return {
        "symbol":   symbol,
        "exchange": exchange,
        "expiry":   selected_expiry,
        "expiries": all_expiries,
        "chain":    chain,
    }
