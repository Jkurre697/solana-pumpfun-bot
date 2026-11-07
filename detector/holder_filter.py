"""
detector/holder_filter.py
Solana RPC helper that returns top-10 holder concentration for a mint.

If top 10 holders own > HOLDER_CONCENTRATION_LIMIT_PCT of supply, the token is
flagged as rug-prone and signal_scorer rejects it.

Calls getTokenLargestAccounts + getTokenSupply on the configured RPC.
Cached for 60s per mint to avoid hammering RPC for re-scored tokens.
"""

import time

import aiohttp
from loguru import logger

from config import HOLDER_CONCENTRATION_LIMIT_PCT, RPC_URL

_cache: dict = {}      # mint -> (timestamp, top10_pct)
_CACHE_TTL = 60        # seconds


async def get_top10_concentration(session: aiohttp.ClientSession, mint: str) -> float | None:
    """Percentage of supply held by the top 10 token accounts.

    Returns a float only when both RPC reads succeed and supply is positive.
    Returns None when the read fails, the payload is an error, supply is
    missing, or the largest-account list is empty. None means "not verified".

    The unlocked scorer still treats None as 0 and does not reject (legacy
    fail-open). The paper-comparison lock rejects None instead.
    """
    now = time.time()
    cached = _cache.get(mint)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]

    try:
        # Fire both calls in parallel
        async with session.post(
            RPC_URL,
            json={
                "jsonrpc": "2.0", "id": 1,
                "method": "getTokenLargestAccounts",
                "params": [mint, {"commitment": "confirmed"}],
            },
            timeout=aiohttp.ClientTimeout(total=4),
        ) as r1:
            largest = await r1.json()

        async with session.post(
            RPC_URL,
            json={
                "jsonrpc": "2.0", "id": 2,
                "method": "getTokenSupply",
                "params": [mint],
            },
            timeout=aiohttp.ClientTimeout(total=4),
        ) as r2:
            supply = await r2.json()

        if not isinstance(largest, dict) or "error" in largest or "result" not in largest:
            return None
        if not isinstance(supply, dict) or "error" in supply or "result" not in supply:
            return None
        accounts = (largest.get("result") or {}).get("value")
        total = ((supply.get("result") or {}).get("value") or {}).get("amount")
        if not isinstance(accounts, list) or not accounts or not total:
            return None
        total_int = int(total)
        if total_int == 0:
            return None

        # Sum top 10 by raw amount
        top10_amount = 0
        for acc in accounts[:10]:
            amt = acc.get("amount") or "0"
            try:
                top10_amount += int(amt)
            except (TypeError, ValueError):
                pass

        pct = (top10_amount / total_int) * 100
        _cache[mint] = (now, pct)
        return pct

    except TimeoutError:
        return None
    except Exception as e:
        logger.debug(f"[HOLDER] {mint[:8]} concentration check error: {e}")
        return None


def concentration_too_high(pct: float) -> bool:
    """Apply the configured threshold."""
    if HOLDER_CONCENTRATION_LIMIT_PCT <= 0:
        return False
    return pct > HOLDER_CONCENTRATION_LIMIT_PCT
