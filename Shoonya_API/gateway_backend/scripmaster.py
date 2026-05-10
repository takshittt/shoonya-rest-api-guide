"""Shoonya NFO scripmaster loader.

Downloads NFO_symbols.txt.zip from Shoonya daily, parses it into a
pandas DataFrame, and exposes helpers for expiry listing and token/strike
map construction.

Cache: scripmaster_nfo.csv in the same directory — refreshed when the file
       is missing or its mtime is from a previous calendar day.
"""

import io
import logging
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

log = logging.getLogger(__name__)

_SCRIPMASTER_URL = "https://api.shoonya.com/NFO_symbols.txt.zip"
_CACHE_PATH = Path(__file__).parent / "scripmaster_nfo.csv"
_DOWNLOAD_TIMEOUT = 30

# Instruments that are options (exclude futures)
_OPT_INSTRUMENTS = frozenset({"OPTIDX", "OPTSTK", "OPTFUT", "OPTCUR"})

# Canonical column name → possible raw CSV header names (lowercased for matching)
_COLUMN_ALIASES: Dict[str, List[str]] = {
    "token":       ["token"],
    "symbol":      ["symbol", "symname", "sym"],
    "tsym":        ["tradingsymbol", "tsym"],
    "instrument":  ["instrument", "instname", "inst"],
    "option_type": ["optiontype", "optt", "option_type"],
    "strike":      ["strikeprice", "strprc", "strike"],
    "expiry":      ["expiry", "exd"],
    "exchange":    ["exchange", "exch"],
    "lot_size":    ["lotsize", "ls"],
}

_REQUIRED = {"token", "symbol", "tsym", "instrument", "option_type", "strike", "expiry"}


def _resolve_columns(df: pd.DataFrame) -> Dict[str, str]:
    """Map canonical names to actual column names found in df.

    Raises ValueError if any required column cannot be matched.
    """
    lower_to_actual = {c.lower().replace(" ", ""): c for c in df.columns}
    resolved: Dict[str, str] = {}
    missing = []
    for canon, aliases in _COLUMN_ALIASES.items():
        found = next((lower_to_actual[a] for a in aliases if a in lower_to_actual), None)
        if found:
            resolved[canon] = found
        elif canon in _REQUIRED:
            missing.append(canon)
    if missing:
        raise ValueError(f"Scripmaster CSV missing required columns: {missing}. "
                         f"Available: {list(df.columns)}")
    return resolved


def _download_and_parse() -> pd.DataFrame:
    log.info("Downloading NFO scripmaster from %s", _SCRIPMASTER_URL)
    resp = requests.get(_SCRIPMASTER_URL, timeout=_DOWNLOAD_TIMEOUT)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        name = zf.namelist()[0]
        text = zf.read(name).decode("utf-8", errors="replace")

    df = pd.read_csv(io.StringIO(text))
    col_map = _resolve_columns(df)

    # Rename to canonical names (only the columns we need)
    rename = {v: k for k, v in col_map.items() if v != k}
    df = df.rename(columns=rename)

    # Keep only option rows
    df = df[df["instrument"].str.upper().isin(_OPT_INSTRUMENTS)].copy()

    # Normalise types
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
    df = df.dropna(subset=["strike"])
    df["token"] = df["token"].astype(str).str.strip()
    for col in ("symbol", "tsym", "option_type", "expiry"):
        df[col] = df[col].astype(str).str.strip()

    df = df.reset_index(drop=True)
    df.to_csv(_CACHE_PATH, index=False)
    log.info("Scripmaster saved to %s (%d option rows)", _CACHE_PATH, len(df))
    return df


def _is_cache_fresh() -> bool:
    if not _CACHE_PATH.exists():
        return False
    mtime = datetime.fromtimestamp(_CACHE_PATH.stat().st_mtime).date()
    return mtime == date.today()


def get_nfo_df(force_refresh: bool = False) -> pd.DataFrame:
    """Return the NFO options DataFrame (cached daily).

    Args:
        force_refresh: Re-download even if cache is fresh.

    Returns:
        DataFrame with canonical columns: token, symbol, tsym, instrument,
        option_type, strike, expiry, plus any additional columns from the CSV.
    """
    if not force_refresh and _is_cache_fresh():
        return pd.read_csv(_CACHE_PATH, dtype={"token": str})

    try:
        return _download_and_parse()
    except Exception as exc:
        log.warning("Scripmaster download failed: %s", exc)
        if _CACHE_PATH.exists():
            log.warning("Using stale cache from %s", _CACHE_PATH)
            return pd.read_csv(_CACHE_PATH, dtype={"token": str})
        raise


def get_expiries(symbol: str, df: pd.DataFrame) -> List[str]:
    """Return expiry date strings for a symbol, sorted nearest-first.

    Args:
        symbol: Base symbol e.g. "NIFTY", "BANKNIFTY".
        df:     DataFrame from get_nfo_df().

    Returns:
        List of expiry strings in the CSV's original format (e.g. "29-MAY-2026"),
        sorted by date ascending. Empty list if symbol not found.
    """
    filtered = df[df["symbol"].str.upper() == symbol.upper()]
    if filtered.empty:
        return []

    unique_expiries = filtered["expiry"].dropna().unique().tolist()

    def _parse(e: str) -> datetime:
        # CSV stores e.g. "29-MAY-2026"; .title() → "29-May-2026" for strptime %b
        try:
            return datetime.strptime(e.title(), "%d-%b-%Y")
        except ValueError:
            return datetime.max

    return sorted(unique_expiries, key=_parse)


def build_token_map(
    symbol: str,
    expiry: str,
    df: pd.DataFrame,
) -> Tuple[Dict[str, Dict], Dict[float, Dict[str, str]]]:
    """Filter scripmaster and build token + strike maps for a symbol/expiry.

    Args:
        symbol: Base symbol e.g. "NIFTY".
        expiry: Expiry string exactly as returned by get_expiries().
        df:     DataFrame from get_nfo_df().

    Returns:
        token_map:  {"NFO|41234": {"token": "41234", "tsym": "...", "exch": "NFO",
                                    "strike": 50000.0, "opttype": "CE", "expiry": "..."}}
        strike_map: {50000.0: {"CE": "41234", "PE": "41235"}}
    """
    mask = (
        (df["symbol"].str.upper() == symbol.upper()) &
        (df["expiry"] == expiry) &
        (df["option_type"].str.upper().isin(["CE", "PE"]))
    )
    subset = df[mask]

    if subset.empty:
        return {}, {}

    token_map: Dict[str, Dict] = {}
    strike_map: Dict[float, Dict[str, str]] = {}

    for _, row in subset.iterrows():
        # Normalise token to a clean integer string (no decimals if stored as float)
        raw_token = str(row["token"]).strip()
        try:
            token_str = str(int(float(raw_token)))
        except (ValueError, OverflowError):
            token_str = raw_token

        opt_type = str(row["option_type"]).upper()
        strike = float(row["strike"])
        key = f"NFO|{token_str}"

        token_map[key] = {
            "token":   token_str,
            "tsym":    str(row["tsym"]),
            "exch":    "NFO",
            "strike":  strike,
            "opttype": opt_type,
            "expiry":  expiry,
        }
        strike_map.setdefault(strike, {})[opt_type] = token_str

    return token_map, strike_map
