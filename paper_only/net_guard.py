"""Block transaction submission and signer imports inside this process."""

from __future__ import annotations

import importlib.abc
import json
import os

BLOCKED_RPC_METHODS = frozenset({
    "sendTransaction",
    "sendRawTransaction",
    "requestAirdrop",
    "simulateTransaction",
})

BLOCKED_URL_SNIPPETS = (
    "pumpportal.fun/api/trade-local",
    "block-engine.jito.wtf",
    "api.telegram.org",
    "/swap",
)

BLOCKED_IMPORTS = frozenset({
    "trader.wallet",
    "trader.executor",
    "trader.pumpportal_executor",
    "trader.local_tx_builder",
})


class PaperSafetyError(RuntimeError):
    pass


def inspect_call(url: str, kwargs: dict | None = None) -> None:
    """Raise if this HTTP call could submit or sign a transaction."""
    if os.getenv("PAPER_COMPARE_LOCK") != "1":
        return
    url_s = str(url)
    for snippet in BLOCKED_URL_SNIPPETS:
        if snippet in url_s:
            raise PaperSafetyError(f"blocked URL under paper lock: {url_s}")
    payload = None if kwargs is None else kwargs.get("json")
    if payload is None and kwargs is not None:
        raw = kwargs.get("data")
        if isinstance(raw, (bytes, bytearray)):
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                if b"sendTransaction" in raw or b"sendRawTransaction" in raw:
                    raise PaperSafetyError("blocked transaction body") from None
        elif isinstance(raw, str) and (
            "sendTransaction" in raw or "sendRawTransaction" in raw
        ):
            raise PaperSafetyError("blocked transaction body")
    items = payload if isinstance(payload, list) else [payload]
    for item in items:
        if isinstance(item, dict) and item.get("method") in BLOCKED_RPC_METHODS:
            raise PaperSafetyError(f"blocked RPC method {item.get('method')}")


_INSTALLED = False
_IMPORTS_BLOCKED = False


def install_network_guard() -> None:
    """Wrap aiohttp so locked processes cannot POST a send method."""
    global _INSTALLED
    if _INSTALLED:
        return
    import aiohttp

    original = aiohttp.ClientSession._request

    async def guarded(self, method, url, **kwargs):
        inspect_call(str(url), kwargs)
        return await original(self, method, url, **kwargs)

    aiohttp.ClientSession._request = guarded  # type: ignore[method-assign]
    _INSTALLED = True


class _SignerImportBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname in BLOCKED_IMPORTS:
            raise PaperSafetyError(
                f"PAPER_COMPARE_LOCK refuses import of {fullname}"
            )
        return None


def install_import_blocker() -> None:
    """Refuse later imports of the live signing modules."""
    global _IMPORTS_BLOCKED
    if _IMPORTS_BLOCKED:
        return
    import sys
    sys.meta_path.insert(0, _SignerImportBlocker())
    _IMPORTS_BLOCKED = True
