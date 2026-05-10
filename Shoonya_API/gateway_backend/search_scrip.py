"""Shoonya SearchScrip API — searches for instruments by text and exchange."""

import json
import requests
from urllib.parse import quote
from typing import Dict, Any, Optional
from shoonya_auth import SHOONYA_API_HOST as SHOONYA_API_BASE

_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "TradingGateway/1.0.0",
}


def search_scrip(
    user_id: str,
    auth_token: str,
    search_text: str,
    exchange: Optional[str] = None,
) -> Dict[str, Any]:
    """POST to /SearchScrip and return the raw response dict."""
    base = SHOONYA_API_BASE.rstrip("/")
    payload: Dict[str, str] = {"uid": user_id, "stext": search_text}
    if exchange:
        payload["exch"] = exchange
    compact = json.dumps(payload, separators=(",", ":"))
    # quote() with safe keeps JSON structural chars intact while encoding
    # special form chars like '&' that would break the jData=...&jKey= format.
    body = f"jData={quote(compact, safe='{}[]\":,/')}&jKey={auth_token}"

    resp = requests.post(
        f"{base}/SearchScrip",
        data=body,
        headers=_HEADERS,
        timeout=30,
    )
    # Shoonya returns 404 when no instruments match the search text.
    if resp.status_code == 404:
        return {"stat": "Not_Ok", "emsg": "No instruments found"}
    resp.raise_for_status()
    return resp.json()
