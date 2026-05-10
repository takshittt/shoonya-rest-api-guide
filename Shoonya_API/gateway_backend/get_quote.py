"""Shoonya GetQuotes API — fetches current quote for a single instrument token."""

import json
import requests
from typing import Any, Dict
from shoonya_auth import SHOONYA_API_HOST as SHOONYA_API_BASE

_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "TradingGateway/1.0.0",
}


def get_quote(
    user_id: str,
    auth_token: str,
    exchange: str,
    token: str,
) -> Dict[str, Any]:
    """POST to /GetQuotes and return the raw response dict.

    Returns fields: stat, lp (last price), oi (open interest),
    v (volume), h (high), l (low), o (open), c (close), ft (feed time).
    """
    base = SHOONYA_API_BASE.rstrip("/")
    payload = {"uid": user_id, "exch": exchange, "token": token}
    compact = json.dumps(payload, separators=(",", ":"))
    body = f"jData={compact}&jKey={auth_token}"

    resp = requests.post(
        f"{base}/GetQuotes",
        data=body,
        headers=_HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()
