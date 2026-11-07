"""Independent paper fills for the comparison book.

These are not trader.paper_executor. Upstream's realistic sim uses
size-dependent slippage, an MEV tax, a 5% fail lottery, and priority fees
of up to 0.001 SOL on buys and 0.005 SOL on sells.

This module uses the comparison cost assumptions:

- fixed notional 0.1 SOL (the curve exposure, not a compounded balance)
- 1% fee per side
- 2% adverse slippage per side
- 0.0005 SOL priority fee per transaction

Buy cash leaving the wallet is notional + fee + priority. The fee and
priority are extra debits, not taken out of the 0.1. Sell cash received is
gross after adverse slippage, minus the 1% fee, minus 0.0005 SOL.
"""

from __future__ import annotations

FIXED_ENTRY_SOL = 0.1
FEE_RATE = 0.01
ADVERSE_SLIPPAGE = 0.02
PRIORITY_FEE_SOL = 0.0005


def buy_fill(mid_price_sol_per_raw: float, notional: float = FIXED_ENTRY_SOL) -> dict:
    """Simulate a buy at a worse price than mid. mid is SOL per raw token unit."""
    if mid_price_sol_per_raw <= 0:
        raise ValueError("mid price must be positive")
    if notional <= 0:
        raise ValueError("notional must be positive")
    effective = mid_price_sol_per_raw * (1.0 + ADVERSE_SLIPPAGE)
    tokens = int(notional / effective)
    fee = notional * FEE_RATE
    priority = PRIORITY_FEE_SOL
    return {
        "notional_sol": notional,
        "mid_price": mid_price_sol_per_raw,
        "effective_price": effective,
        "tokens": tokens,
        "fee_sol": fee,
        "priority_sol": priority,
        "cash_debit": notional + fee + priority,
        "slippage": ADVERSE_SLIPPAGE,
    }


def sell_fill(tokens: int, mid_price_sol_per_raw: float) -> dict:
    """Simulate a sell at a worse price than mid."""
    if tokens <= 0:
        raise ValueError("tokens must be positive")
    if mid_price_sol_per_raw <= 0:
        raise ValueError("mid price must be positive")
    gross = tokens * mid_price_sol_per_raw * (1.0 - ADVERSE_SLIPPAGE)
    fee = gross * FEE_RATE
    priority = PRIORITY_FEE_SOL
    received = gross - fee - priority
    if received < 0:
        received = 0.0
    return {
        "tokens": tokens,
        "mid_price": mid_price_sol_per_raw,
        "gross_sol": gross,
        "fee_sol": fee,
        "priority_sol": priority,
        "sol_received": received,
        "slippage": ADVERSE_SLIPPAGE,
    }
