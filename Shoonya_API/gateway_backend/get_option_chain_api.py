"""Shoonya GetOptionChain API — returns CE/PE pairs around a given strike price."""

import json
import requests
from urllib.parse import quote
from typing import Any, Dict
from shoonya_auth import SHOONYA_API_HOST as SHOONYA_API_BASE

_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "TradingGateway/1.0.0",
}


def get_option_chain_api(
    user_id: str,
    auth_token: str,
    exchange: str,
    tsym: str,
    strikeprice: float,
    count: int = 15,
) -> Dict[str, Any]:
    """POST to /GetOptionChain and return the raw response dict.

    Args:
        tsym: The futures trading symbol for the desired expiry
              (e.g. "BANKNIFTY26JUN25F" or "CRUDEOIL25MAYF").
        strikeprice: Center/ATM strike price.
        count: Number of strikes above AND below the center to return.

    Returns: {"stat": "Ok", "values": [{token, tsym, exch, optt, strprc, ...}, ...]}
    """
    base = SHOONYA_API_BASE.rstrip("/")
    payload = {
        "uid":    user_id,
        "actid":  user_id,
        "exch":   exchange,
        "tsym":   tsym,
        "strprc": str(strikeprice),
        "cnt":    str(count),
    }
    compact = json.dumps(payload, separators=(",", ":"))
    body = f"jData={quote(compact, safe='{}[]\":,/')}&jKey={auth_token}"

    resp = requests.post(
        f"{base}/GetOptionChain",
        data=body,
        headers=_HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()
