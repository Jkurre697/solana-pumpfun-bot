"""Fixed 0.1 SOL entries. No compounding and no clipped size."""

from __future__ import annotations

from paper_only.costs import FIXED_ENTRY_SOL


async def fixed_entry_size(risk_manager, score: int, symbol: str | None) -> tuple[float, str]:
    """Honor upstream risk gates, then require the size to be exactly 0.1.

    If the sizer clips, scales, or otherwise returns any other positive size,
    the trade is skipped. A smaller 'almost 0.1' entry is not taken.
    """
    size, reason = await risk_manager.calculate_position_size(score, symbol=symbol)
    if reason:
        return 0.0, reason
    if abs(float(size) - FIXED_ENTRY_SOL) > 1e-9:
        return 0.0, "fixed_size_unavailable"
    return FIXED_ENTRY_SOL, ""
