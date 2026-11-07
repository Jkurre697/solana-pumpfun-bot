"""Paper executor with no signing surface.

Fills come from paper_only.costs. Prices are marks supplied by the caller.
Nothing in this class imports solders, builds a transaction, or talks to a
trader endpoint.
"""

from __future__ import annotations

import time

from paper_only.costs import FIXED_ENTRY_SOL, buy_fill, sell_fill


def mid_from_launch(token: dict | None) -> float:
    """SOL per raw token unit, same conversion as trader.paper_executor.buy.

    PumpPortal's vTokensInBondingCurve is treated as UI tokens and pump.fun
    tokens use 6 decimals. Returns 0 when the launch payload has no reserves.
    """
    if not token:
        return 0.0
    v_sol = float(token.get("v_sol_in_bonding") or 0)
    v_tokens = float(token.get("v_tokens_in_bonding") or 0)
    if v_sol <= 0 or v_tokens <= 0:
        return 0.0
    return v_sol / (v_tokens * 1_000_000)


class ComparisonPaperExecutor:
    def __init__(self, wallet) -> None:
        self.wallet = wallet
        self._prices: dict[str, float] = {}
        self._held: dict[str, int] = {}

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def update_price(self, mint: str, price_per_raw: float) -> None:
        if price_per_raw and price_per_raw > 0:
            self._prices[mint] = float(price_per_raw)

    async def prebuild_sell_tx(self, token_mint: str):
        """Compat shim. There is no transaction to prebuild."""
        return None

    def _resolve_tokens(self, mint: str, raw) -> int:
        held = self._held.get(mint, 0)
        if isinstance(raw, str):
            text = raw.strip()
            if text.endswith("%"):
                try:
                    pct = float(text[:-1])
                except ValueError:
                    return 0
                return max(0, int(held * (pct / 100.0)))
            try:
                return max(0, int(float(text)))
            except ValueError:
                return 0
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 0

    async def buy(self, token_mint: str, sol_amount: float, token: dict | None = None) -> dict:
        now = time.time()
        if abs(float(sol_amount) - FIXED_ENTRY_SOL) > 1e-9:
            return {
                "success": False,
                "error": "non_fixed_size",
                "venue": "paper",
                "type": "buy",
                "mint": token_mint,
                "timestamp": now,
            }
        mid = mid_from_launch(token) or self._prices.get(token_mint, 0.0)
        if mid <= 0:
            return {
                "success": False,
                "error": "no_price",
                "venue": "paper",
                "type": "buy",
                "mint": token_mint,
                "timestamp": now,
            }
        fill = buy_fill(mid, FIXED_ENTRY_SOL)
        if fill["tokens"] <= 0:
            return {
                "success": False,
                "error": "zero_fill",
                "venue": "paper",
                "type": "buy",
                "mint": token_mint,
                "timestamp": now,
            }
        balance = await self.wallet.get_sol_balance()
        if balance < fill["cash_debit"]:
            return {
                "success": False,
                "error": "insufficient_paper_balance",
                "venue": "paper",
                "type": "buy",
                "mint": token_mint,
                "timestamp": now,
            }
        self.wallet.deduct(fill["cash_debit"])
        self._held[token_mint] = self._held.get(token_mint, 0) + fill["tokens"]
        self._prices[token_mint] = mid
        return {
            "success": True,
            "signature": f"PAPER_{token_mint[:8]}_{int(now)}",
            "type": "buy",
            "mint": token_mint,
            "sol_spent": FIXED_ENTRY_SOL,
            "tokens_expected": fill["tokens"],
            "fee_sol": fill["fee_sol"],
            "priority_sol": fill["priority_sol"],
            "cash_debit": fill["cash_debit"],
            "venue": "paper",
            "timestamp": now,
        }

    async def sell(
        self,
        token_mint: str,
        token_amount,
        reason: str = "exit",
        prebuilt_tx: bytes | None = None,
        price_history: list | None = None,
    ) -> dict:
        del prebuilt_tx, price_history
        now = time.time()
        amount = self._resolve_tokens(token_mint, token_amount)
        mid = self._prices.get(token_mint, 0.0)
        if amount <= 0 or mid <= 0:
            return {
                "success": False,
                "error": "no_price" if mid <= 0 else "zero_amount",
                "venue": "paper",
                "type": "sell",
                "mint": token_mint,
                "reason": reason,
                "timestamp": now,
            }
        fill = sell_fill(amount, mid)
        remaining = self._held.get(token_mint, 0) - amount
        if remaining > 0:
            self._held[token_mint] = remaining
        else:
            self._held.pop(token_mint, None)
        self.wallet.credit(fill["sol_received"])
        return {
            "success": True,
            "signature": f"PAPER_SELL_{token_mint[:8]}_{int(now)}",
            "type": "sell",
            "mint": token_mint,
            "reason": reason,
            "sol_received": fill["sol_received"],
            "fee_sol": fill["fee_sol"],
            "priority_sol": fill["priority_sol"],
            "tokens_sold": amount,
            "venue": "paper",
            "timestamp": now,
        }
