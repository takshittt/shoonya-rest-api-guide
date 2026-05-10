"""Shoonya UserDetails API — fetches full user profile."""

import json
import requests
from typing import Dict, Any
from shoonya_auth import SHOONYA_API_HOST as SHOONYA_API_BASE

_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "TradingGateway/1.0.0",
}


def get_user_details(user_id: str, auth_token: str) -> Dict[str, Any]:
    """POST to /NorenWClientAPI/UserDetails and return the raw response dict."""
    base = SHOONYA_API_BASE.rstrip("/")
    payload = {"uid": user_id}
    compact = json.dumps(payload, separators=(",", ":"))
    body = f"jData={compact}&jKey={auth_token}"

    resp = requests.post(
        f"{base}/UserDetails",
        data=body,
        headers=_HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()
