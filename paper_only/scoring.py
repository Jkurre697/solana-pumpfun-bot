"""Paper-comparison scoring data flow.

The frozen four-factor math in SignalScorer is unchanged. This module
only repairs inputs the monitor left stale, records which inputs were
actually present, and schedules a bounded rescore when a rejection can
still change because data was missing or the launch snapshot was young.

It does not lower the score threshold, invent prices, or skip the
holder and freeze-authority gates.
"""

from __future__ import annotations

import asyncio
import json
import os
import time

from loguru import logger

from analyzer.signal_scorer import SignalScorer

REASSESS_INTERVAL_S = 30.0
REASSESS_MAX = 8
REASSESS_BUDGET_S = 600.0

# These rejects do not become true later. Score and unread-risk rejects can.
RESCORE_REASONS = frozenset({
    "holder_data_unavailable",
    "freeze_authority_unknown",
})
PERMANENT_PREFIXES = (
    "no_symbol",
    "sym_blacklist_",
    "name_blacklist",
    "big_init_buy_",
    "creator_blacklisted",
    "whale_init_",
    "rug_pattern_overload_",
    "dead_hours_",
    "regime_dead",
    "freeze_authority_set",
    "top10_",
)


def refresh_score_age(token: dict, *, now: float | None = None) -> float | None:
    """Set age_minutes from the create timestamp. Do not invent other fields."""
    created = token.get("created_ts")
    if created is None:
        token["age_source"] = "missing_created_ts"
        return None
    try:
        age_min = (float(now if now is not None else time.time()) - float(created)) / 60.0
    except (TypeError, ValueError):
        token["age_source"] = "bad_created_ts"
        return None
    if age_min < 0:
        age_min = 0.0
    token["age_minutes"] = age_min
    token["age_source"] = "wall_since_create"
    return age_min


def should_rescore(token: dict, attempts: int, *, elapsed_s: float) -> bool:
    """True when another pass might see data the first pass could not."""
    if attempts >= REASSESS_MAX or elapsed_s > REASSESS_BUDGET_S:
        return False
    if token.get("paper_buy_queued"):
        return False
    reason = str(token.get("reject_reason") or "")
    if not reason:
        return False
    if reason.startswith(PERMANENT_PREFIXES):
        return False
    if reason.startswith("score_") or reason in RESCORE_REASONS:
        return True
    return False


def input_availability(token: dict) -> dict:
    """Say whether each scorer input was observed. Defaults are not data."""
    holder = token.get("holder_check")
    freeze = token.get("freeze_check")
    return {
        "age_source": token.get("age_source", "launch_stamp_zero"),
        "age_minutes": token.get("age_minutes"),
        "dex": "present" if "dex_pair_address" in token else "unavailable",
        "price_change_5m": (
            "present" if "price_change_5m" in token else "default_zero"
        ),
        "holder_count": (
            "present" if "holder_count" in token else "default_zero"
        ),
        "pumpfun_tracker": (
            "present" if "pf_reply_count" in token else "unavailable"
        ),
        "curve_source": "launch_snapshot",
        "holder_check": holder if holder else "not_reached",
        "freeze_check": freeze if freeze else "not_reached",
        "reject_reason": token.get("reject_reason") or "",
    }


def diagnostic_row(token: dict, *, attempt: int) -> dict:
    breakdown = token.get("score_breakdown") or {}
    return {
        "ts": time.time(),
        "mint": token.get("mint"),
        "symbol": token.get("symbol"),
        "attempt": attempt,
        "score": token.get("score"),
        "raw_score": token.get("raw_score"),
        "threshold_unchanged": True,
        "breakdown": {
            "creator": breakdown.get("creator"),
            "bonding_curve": breakdown.get("bonding_curve"),
            "community": breakdown.get("community"),
            "price_momentum": breakdown.get("price_momentum"),
            "fusion": breakdown.get("fusion", 0),
            "rug_pattern_match": breakdown.get("rug_pattern_match", 0),
        },
        "inputs": input_availability(token),
        "queued_buy": bool(token.get("paper_buy_queued")),
    }


def write_diagnostic(token: dict, *, attempt: int) -> dict:
    row = diagnostic_row(token, attempt=attempt)
    parts = row["breakdown"]
    inputs = row["inputs"]
    logger.info(
        "[SCORE PARTS] {} | attempt={} | score={} | "
        "creator={} curve={} community={} momentum={} fusion={} rug={} | "
        "dex={} tracker={} price5m={} holders={} holder_check={} "
        "freeze_check={} age={}:{} | reject={}",
        token.get("symbol"),
        attempt,
        token.get("score"),
        parts.get("creator"),
        parts.get("bonding_curve"),
        parts.get("community"),
        parts.get("price_momentum"),
        parts.get("fusion"),
        parts.get("rug_pattern_match"),
        inputs["dex"],
        inputs["pumpfun_tracker"],
        inputs["price_change_5m"],
        inputs["holder_count"],
        inputs["holder_check"],
        inputs["freeze_check"],
        inputs["age_source"],
        inputs["age_minutes"],
        inputs["reject_reason"] or "-",
    )
    try:
        os.makedirs("logs", exist_ok=True)
        with open("logs/score_diagnostics.jsonl", "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
    except OSError as exc:
        logger.debug(f"[SCORE PARTS] write failed: {exc}")
    return row


class PaperSignalScorer(SignalScorer):
    """SignalScorer plus age refresh, diagnostics, and bounded rescore."""

    def __init__(self, raw_queue, trade_queue, executor=None):
        super().__init__(raw_queue, trade_queue, executor=executor)
        self._attempts: dict[str, int] = {}
        self._first_mono: dict[str, float] = {}
        self._buy_once: set[str] = set()

    async def _score_token(self, token: dict):
        mint = str(token.get("mint") or "")
        if mint and mint in self._buy_once:
            return
        if mint and mint not in self._first_mono:
            self._first_mono[mint] = time.monotonic()
        attempt = self._attempts.get(mint, 0) + 1
        self._attempts[mint] = attempt
        token["paper_rescore_attempt"] = attempt
        await super()._score_token(token)
        if token.get("paper_buy_queued") and mint:
            self._buy_once.add(mint)
        write_diagnostic(token, attempt=attempt)
        if mint and should_rescore(
            token,
            attempt,
            elapsed_s=time.monotonic() - self._first_mono.get(mint, time.monotonic()),
        ):
            asyncio.create_task(self._rescore(dict(token)))

    async def _rescore(self, token: dict):
        await asyncio.sleep(REASSESS_INTERVAL_S)
        token.pop("reject_reason", None)
        token.pop("paper_buy_queued", None)
        token.pop("score_breakdown", None)
        await self._score_token(token)


class BuyMarkQueue:
    """Mark a token when the scorer queues a buy, and drop duplicate mints."""

    def __init__(self, inner):
        self._inner = inner
        self._seen: set[str] = set()

    def _mark(self, item):
        if not isinstance(item, dict):
            return item
        mint = str(item.get("mint") or "")
        if mint and mint in self._seen:
            return None
        if mint:
            self._seen.add(mint)
        item["paper_buy_queued"] = True
        return item

    async def put(self, item):
        marked = self._mark(item)
        if marked is None:
            return
        await self._inner.put(marked)

    def put_nowait(self, item):
        marked = self._mark(item)
        if marked is None:
            return
        self._inner.put_nowait(marked)

    def __getattr__(self, name):
        return getattr(self._inner, name)
