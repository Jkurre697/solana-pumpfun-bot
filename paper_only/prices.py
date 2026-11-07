"""Read-only price marks.

Copied in structure from main._bonding_curve_price and the DexScreener
branch of main._get_token_price. Jupiter's quote API is not called.

getAccountInfo is the only RPC method used here. The network guard rejects
transaction-submission methods. Primary is the public Solana RPC.
PublicNode is the backup.
"""

from __future__ import annotations

import base64
import struct

import aiohttp

from paper_only.frozen import PUBLIC_RPC_BACKUP, PUBLIC_RPC_PRIMARY

_PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
_ALLOWED_METHODS = frozenset({"getAccountInfo"})


def _rpc_urls() -> list[str]:
    urls = [PUBLIC_RPC_PRIMARY]
    if PUBLIC_RPC_BACKUP not in urls:
        urls.append(PUBLIC_RPC_BACKUP)
    return urls


async def _post_get_account_info(
    session: aiohttp.ClientSession,
    url: str,
    params: list,
) -> dict | None:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": params,
    }
    if payload["method"] not in _ALLOWED_METHODS:
        raise RuntimeError("price reader attempted a non-read RPC method")
    try:
        async with session.post(
            url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=4),
        ) as resp:
            if resp.status != 200:
                return None
            return await resp.json()
    except (TimeoutError, aiohttp.ClientError):
        return None


async def bonding_curve_price(session: aiohttp.ClientSession, mint: str) -> float:
    """SOL per raw token unit from the pump.fun bonding-curve account."""
    try:
        from solders.pubkey import Pubkey
    except ImportError:
        return 0.0
    try:
        program = Pubkey.from_string(_PUMP_PROGRAM_ID)
        curve, _bump = Pubkey.find_program_address(
            [b"bonding-curve", bytes(Pubkey.from_string(mint))],
            program,
        )
    except Exception:
        return 0.0
    params = [str(curve), {"encoding": "base64", "commitment": "confirmed"}]
    for url in _rpc_urls():
        data = await _post_get_account_info(session, url, params)
        if not data:
            continue
        value = (data.get("result") or {}).get("value")
        if not value:
            continue
        try:
            raw = base64.b64decode(value["data"][0])
            v_tok, v_sol = struct.unpack_from("<QQ", raw, 8)
        except (KeyError, TypeError, ValueError, struct.error):
            continue
        if v_tok == 0:
            continue
        return (v_sol / 1e9) / v_tok
    return 0.0


async def dexscreener_price(session: aiohttp.ClientSession, mint: str) -> float:
    """SOL per raw unit from DexScreener priceNative, 6-decimal pump tokens."""
    url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status != 200:
                return 0.0
            data = await resp.json()
    except (TimeoutError, aiohttp.ClientError):
        return 0.0
    pairs = data.get("pairs") or []
    if not pairs:
        return 0.0
    try:
        price_native = float(pairs[0].get("priceNative") or 0)
    except (TypeError, ValueError):
        return 0.0
    if price_native <= 0:
        return 0.0
    return price_native / 1_000_000


async def read_price(session: aiohttp.ClientSession, mint: str) -> float:
    price = await bonding_curve_price(session, mint)
    if price > 0:
        return price
    return await dexscreener_price(session, mint)
