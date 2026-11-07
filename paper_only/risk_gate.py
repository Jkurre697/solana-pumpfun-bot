"""Fail-closed entry gate for the paper comparison.

Upstream SignalScorer, with the lock unset, treats a failed holder read as
0% concentration and a failed freeze-authority read as safe. Those entries
would otherwise be ordinary buys and could close in the clean bucket.

The comparison requires both reads to have succeeded:
- holder_check == "ok" (a real top-10 percentage, not a timeout)
- freeze_check == "safe" (account visible and freeze authority null)

Anything else is blocked before a position is opened. Blocked names are
logged separately and are not clean trades. This is a safety override on
top of the frozen thresholds, not a second strategy.
"""

from __future__ import annotations


def entry_block_reason(token: dict) -> str:
    """Return a reject reason, or "" when the required risk reads succeeded."""
    if token.get("holder_check") != "ok":
        return "holder_data_unavailable"
    freeze = token.get("freeze_check")
    if freeze == "safe":
        return ""
    if freeze == "set":
        return "freeze_authority_set"
    return "freeze_authority_unknown"
