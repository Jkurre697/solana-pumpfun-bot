"""Side ledger that keeps freeze-hit, data-gap, and clean legs apart.

RiskManager still writes its own logs. This file does not rewrite them.
Bucket PnL is not a profit result. Legs that overlap a host freeze are
not mixed into the clean bucket.
"""

from __future__ import annotations

import json
import os
import time

from paper_only.feedhealth import FeedHealth

_BUCKETS = ("clean", "freeze_hit", "data_gap")


class CompareBook:
    def __init__(self, health: FeedHealth) -> None:
        self.health = health
        self._opens: dict[str, dict] = {}
        self.counts = {name: {"n": 0, "risk_pnl_sol": 0.0, "cash_pnl_sol": 0.0} for name in _BUCKETS}
        self.blocked = {"n": 0, "by_reason": {}}

    def on_open(self, mint: str, result: dict) -> None:
        self._opens[mint] = {
            "entry_wall": time.time(),
            "notional": float(result.get("sol_spent") or 0.0),
            "buy_fee": float(result.get("fee_sol") or 0.0),
            "buy_priority": float(result.get("priority_sol") or 0.0),
        }

    def tag_record(self, record: dict) -> dict:
        mint = record.get("mint", "")
        meta = self._opens.get(mint) or {}
        entry = float(record.get("entry_time") or meta.get("entry_wall") or time.time())
        exit_t = float(record.get("exit_time") or time.time())
        bucket = self.health.bucket(entry, exit_t)
        notional = float(meta.get("notional") or 0.0)
        invested = float(record.get("sol_invested") or 0.0)
        fraction = (invested / notional) if notional > 0 else 1.0
        buy_drag = (float(meta.get("buy_fee") or 0.0) + float(meta.get("buy_priority") or 0.0)) * fraction
        risk_pnl = float(record.get("pnl_sol") or 0.0)
        tagged = {
            "mint": mint,
            "symbol": record.get("symbol"),
            "reason": record.get("reason"),
            "partial": bool(record.get("partial")),
            "entry_time": entry,
            "exit_time": exit_t,
            "sol_invested": invested,
            "sol_received": record.get("sol_received"),
            "risk_pnl_sol": risk_pnl,
            "buy_cost_allocated_sol": buy_drag,
            "cash_pnl_sol": risk_pnl - buy_drag,
            "bucket": bucket,
            "score": record.get("score"),
        }
        self.counts[bucket]["n"] += 1
        self.counts[bucket]["risk_pnl_sol"] += risk_pnl
        self.counts[bucket]["cash_pnl_sol"] += tagged["cash_pnl_sol"]
        if not record.get("partial"):
            self._opens.pop(mint, None)
        self._append(tagged)
        self.write_summary()
        return tagged

    def _append(self, tagged: dict) -> None:
        os.makedirs("logs", exist_ok=True)
        with open("logs/compare_trades.jsonl", "a", encoding="utf-8") as handle:
            handle.write(json.dumps(tagged) + "\n")

    def note_blocked(self, token: dict, reason: str) -> None:
        """Record an entry that never opened because a risk read was missing.

        These rows are not trades and are not in the clean bucket.
        """
        self.blocked["n"] += 1
        reasons = self.blocked["by_reason"]
        reasons[reason] = int(reasons.get(reason, 0)) + 1
        os.makedirs("logs", exist_ok=True)
        row = {
            "mint": token.get("mint"),
            "symbol": token.get("symbol"),
            "reason": reason,
            "holder_check": token.get("holder_check"),
            "freeze_check": token.get("freeze_check"),
            "ts": time.time(),
            "counts_as_trade": False,
            "bucket": "blocked_missing_risk",
        }
        with open("logs/blocked_entries.jsonl", "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        self.write_summary()

    def write_summary(self) -> None:
        os.makedirs("logs", exist_ok=True)
        payload = {
            "note": (
                "Buckets are mutually exclusive. Do not add them into a "
                "profit claim. cash_pnl_sol subtracts the buy-side 1% fee "
                "and 0.0005 SOL priority from the risk manager's pnl, which "
                "does not include those entry debits."
            ),
            "buckets": self.counts,
            "blocked_missing_risk": self.blocked,
            "blocked_missing_risk_note": (
                "Not trades. Holder or freeze-authority data was missing, "
                "so the entry was refused. Do not add these to clean pnl."
            ),
            "open_positions": len(self._opens),
        }
        tmp = "logs/compare_buckets.json.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp, "logs/compare_buckets.json")

    def write_health(self) -> None:
        os.makedirs("logs", exist_ok=True)
        tmp = "logs/feed_health.json.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(self.health.snapshot(), handle, indent=2)
        os.replace(tmp, "logs/feed_health.json")
