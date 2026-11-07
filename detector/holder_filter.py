"""
detector/holder_filter.py
Solana RPC helper that returns top-10 holder concentration for a mint.

If top 10 holders own > HOLDER_CONCENTRATION_LIMIT_PCT of supply, the token is
flagged as rug-prone and signal_scorer rejects it.

Calls getTokenLargestAccounts + getTokenSupply on the configured RPC only.
The RPC list includes every large token account it returns. On pump.fun that
includes the bonding-curve token account, which holds unsold supply. This
strategy does not subtract that protocol account and does not invent a
replacement concentration. A missing or refused read is unavailable, not 0%.

A 429 or other refusal is logged and then left alone: no second endpoint and
no immediate retry. A short backoff skips further largest-account calls so
the process does not hammer the same restricted method.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import aiohttp
from loguru import logger

from config import HOLDER_CONCENTRATION_LIMIT_PCT, RPC_URL

_cache: dict = {}      # mint -> (timestamp, top10_pct)
_CACHE_TTL = 60        # seconds
_BACKOFF_S = 60.0
_backoff_until = 0.0


@dataclass(frozen=True)
class HolderRead:
    """One attempt to read top-10 concentration. pct is set only when verified."""

    pct: float | None
    http_status: int | None = None
    rpc_code: int | None = None
    rpc_message: str = ""
    endpoint_host: str = ""
    skipped_call: bool = False

    def as_dict(self) -> dict:
        return {
            "http_status": self.http_status,
            "rpc_code": self.rpc_code,
            "rpc_message": self.rpc_message,
            "endpoint_host": self.endpoint_host,
            "skipped_call": self.skipped_call,
            "pct": self.pct,
        }

    def summary(self) -> str:
        host = self.endpoint_host or "rpc"
        if self.skipped_call:
            return f"http={self.http_status} host={host} skipped_call backoff"
        return (
            f"http={self.http_status} rpc={self.rpc_code} "
            f"host={host} msg={self.rpc_message or '-'}"
        )


def reset_holder_backoff_for_tests() -> None:
    global _backoff_until
    _backoff_until = 0.0
    _cache.clear()


def _host(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except ValueError:
        return ""


def _clean_message(text: str) -> str:
    flat = " ".join((text or "").split())
    return flat[:180]


def top10_concentration_pct(accounts: list, supply_amount: int) -> float | None:
    """Sum the RPC's top accounts over supply.

    Every returned account counts, including a pump.fun bonding-curve
    token account. There is no protocol-account exclusion in this strategy.
    """
    if supply_amount <= 0 or not isinstance(accounts, list) or not accounts:
        return None
    total = 0
    for acc in accounts[:10]:
        if not isinstance(acc, dict):
            continue
        try:
            total += int(acc.get("amount") or "0")
        except (TypeError, ValueError):
            continue
    return (total / supply_amount) * 100


def _json_or_text(raw: str) -> dict | None:
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def interpret_rpc_body(http_status: int | None, raw: str, *, host: str) -> HolderRead | None:
    """Return a failed read, or None when the body is a usable success."""
    parsed = _json_or_text(raw)
    if http_status is not None and http_status != 200:
        message = ""
        code = None
        if parsed and isinstance(parsed.get("error"), dict):
            code = parsed["error"].get("code")
            message = _clean_message(str(parsed["error"].get("message") or ""))
        if not message:
            message = _clean_message(raw) or f"http_{http_status}"
        try:
            code_int = int(code) if code is not None else None
        except (TypeError, ValueError):
            code_int = None
        return HolderRead(
            pct=None,
            http_status=http_status,
            rpc_code=code_int,
            rpc_message=message,
            endpoint_host=host,
        )
    if parsed is None:
        return HolderRead(
            pct=None,
            http_status=http_status,
            rpc_message=_clean_message(raw) or "unparsed_body",
            endpoint_host=host,
        )
    if "error" in parsed or "result" not in parsed:
        err = parsed.get("error") if isinstance(parsed.get("error"), dict) else {}
        code = err.get("code")
        try:
            code_int = int(code) if code is not None else None
        except (TypeError, ValueError):
            code_int = None
        return HolderRead(
            pct=None,
            http_status=http_status,
            rpc_code=code_int,
            rpc_message=_clean_message(str(err.get("message") or "rpc_error")),
            endpoint_host=host,
        )
    return None


def _arm_backoff(read: HolderRead) -> HolderRead:
    global _backoff_until
    limited = read.http_status == 429 or read.rpc_code == 429
    if limited:
        _backoff_until = time.time() + _BACKOFF_S
    logger.info(f"[HOLDER] unavailable | {read.summary()}")
    return read


async def _read_body(resp) -> tuple[int | None, str]:
    status = getattr(resp, "status", 200)
    if hasattr(resp, "text"):
        raw = await resp.text()
        return status, raw if isinstance(raw, str) else str(raw)
    data = await resp.json()
    return status, json.dumps(data)


async def get_holder_read(session: aiohttp.ClientSession, mint: str) -> HolderRead:
    """One read against RPC_URL. Does not try another host."""
    global _backoff_until
    host = _host(RPC_URL)
    now = time.time()
    if now < _backoff_until:
        return HolderRead(
            pct=None,
            http_status=429,
            rpc_code=429,
            rpc_message="backoff_after_rate_limit",
            endpoint_host=host,
            skipped_call=True,
        )
    cached = _cache.get(mint)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return HolderRead(pct=cached[1], http_status=200, endpoint_host=host)

    try:
        async with session.post(
            RPC_URL,
            json={
                "jsonrpc": "2.0", "id": 1,
                "method": "getTokenLargestAccounts",
                "params": [mint, {"commitment": "confirmed"}],
            },
            timeout=aiohttp.ClientTimeout(total=4),
        ) as largest_resp:
            largest_status, largest_raw = await _read_body(largest_resp)
        failed = interpret_rpc_body(largest_status, largest_raw, host=host)
        if failed is not None:
            return _arm_backoff(failed)

        async with session.post(
            RPC_URL,
            json={
                "jsonrpc": "2.0", "id": 2,
                "method": "getTokenSupply",
                "params": [mint],
            },
            timeout=aiohttp.ClientTimeout(total=4),
        ) as supply_resp:
            supply_status, supply_raw = await _read_body(supply_resp)
        failed = interpret_rpc_body(supply_status, supply_raw, host=host)
        if failed is not None:
            return _arm_backoff(failed)

        largest = json.loads(largest_raw)
        supply = json.loads(supply_raw)
        accounts = (largest.get("result") or {}).get("value")
        amount = ((supply.get("result") or {}).get("value") or {}).get("amount")
        try:
            supply_amount = int(amount)
        except (TypeError, ValueError):
            supply_amount = 0
        pct = top10_concentration_pct(accounts if isinstance(accounts, list) else [], supply_amount)
        if pct is None:
            return _arm_backoff(HolderRead(
                pct=None,
                http_status=200,
                rpc_message="empty_or_zero_supply",
                endpoint_host=host,
            ))
        _cache[mint] = (now, pct)
        return HolderRead(pct=pct, http_status=200, endpoint_host=host)
    except TimeoutError:
        return _arm_backoff(HolderRead(
            pct=None, rpc_message="timeout", endpoint_host=host,
        ))
    except Exception as exc:
        return _arm_backoff(HolderRead(
            pct=None,
            rpc_message=_clean_message(f"{type(exc).__name__}: {exc}"),
            endpoint_host=host,
        ))


async def get_top10_concentration(session: aiohttp.ClientSession, mint: str) -> float | None:
    """Percentage when verified, otherwise None. See get_holder_read."""
    return (await get_holder_read(session, mint)).pct


def concentration_too_high(pct: float) -> bool:
    """Apply the configured threshold."""
    if HOLDER_CONCENTRATION_LIMIT_PCT <= 0:
        return False
    return pct > HOLDER_CONCENTRATION_LIMIT_PCT
