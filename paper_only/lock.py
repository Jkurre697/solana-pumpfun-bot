"""Apply the paper-comparison environment lock.

Call this before importing config.py. python-dotenv is disabled while the
lock is set, and live signing modules refuse to construct.
"""

from __future__ import annotations

import os

from paper_only.frozen import BLANKED_SECRETS, COMPARISON_OVERRIDES, FROZEN_UPSTREAM

_KEYED_RPC_MARKERS = (
    "api-key",
    "api_key",
    "helius",
    "alchemy",
    "quiknode",
    "quicknode",
    "triton.one",
)


def install_lock() -> None:
    """Force paper mode, frozen thresholds, and empty credentials."""
    os.environ["PAPER_COMPARE_LOCK"] = "1"
    for key, value in FROZEN_UPSTREAM.items():
        os.environ[key] = value
    for key, value in COMPARISON_OVERRIDES.items():
        os.environ[key] = value
    for key, value in BLANKED_SECRETS.items():
        os.environ[key] = value
    rpc = os.environ.get("RPC_URL", "")
    lowered = rpc.lower()
    for marker in _KEYED_RPC_MARKERS:
        if marker in lowered:
            raise RuntimeError(f"PAPER_COMPARE_LOCK refuses keyed RPC URL ({marker})")


def paper_compare_locked() -> bool:
    return os.getenv("PAPER_COMPARE_LOCK") == "1"
