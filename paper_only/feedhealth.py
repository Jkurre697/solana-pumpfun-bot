"""Host-freeze and market-data-gap tracker.

Host freeze: the event-loop heartbeat woke up late. A stall of at least
FREEZE_DETECT_S is recorded, new entries pause for ENTRY_PAUSE_S, and a
stall of at least FLATTEN_FREEZE_S requests a flatten.

Data gap: silence on the PumpPortal stream of at least WS_GAP_S. Gaps are
counted separately from freezes. A quiet market can look like a gap; the
stat is a feed-health record, not proof of a missed edge.
"""

from __future__ import annotations

import time

HEARTBEAT_INTERVAL_S = 1.0
FREEZE_DETECT_S = 5.0
ENTRY_PAUSE_S = 90.0
FLATTEN_FREEZE_S = 300.0
WS_GAP_S = 15.0


class FeedHealth:
    def __init__(self) -> None:
        now = time.monotonic()
        self._last_beat = now
        self._last_ws = now
        self._ws_armed = False
        self._seq = 0
        self.entry_pause_until = 0.0
        self.pending_flatten = False
        self.freezes: list[dict] = []
        self.gaps: list[dict] = []

    def observe_stall(self, stall_s: float, *, wall_end: float | None = None) -> dict | None:
        if stall_s < FREEZE_DETECT_S:
            return None
        self._seq += 1
        end = time.time() if wall_end is None else wall_end
        rec = {
            "id": self._seq,
            "kind": "host_freeze",
            "stall_s": round(float(stall_s), 3),
            "wall_start": end - float(stall_s),
            "wall_end": end,
            "flatten": float(stall_s) >= FLATTEN_FREEZE_S,
        }
        self.freezes.append(rec)
        self.entry_pause_until = time.monotonic() + ENTRY_PAUSE_S
        if rec["flatten"]:
            self.pending_flatten = True
        return rec

    def heartbeat(self) -> dict | None:
        now = time.monotonic()
        elapsed = now - self._last_beat
        self._last_beat = now
        return self.observe_stall(elapsed - HEARTBEAT_INTERVAL_S)

    def note_ws_message(self) -> dict | None:
        now = time.monotonic()
        if not self._ws_armed:
            self._ws_armed = True
            self._last_ws = now
            return None
        gap = now - self._last_ws
        self._last_ws = now
        if gap < WS_GAP_S:
            return None
        self._seq += 1
        end = time.time()
        rec = {
            "id": self._seq,
            "kind": "data_gap",
            "gap_s": round(gap, 3),
            "wall_start": end - gap,
            "wall_end": end,
        }
        self.gaps.append(rec)
        return rec

    def entries_paused(self) -> bool:
        return time.monotonic() < self.entry_pause_until

    def consume_flatten(self) -> bool:
        if not self.pending_flatten:
            return False
        self.pending_flatten = False
        return True

    @staticmethod
    def _overlaps(events: list[dict], start_wall: float, end_wall: float) -> bool:
        for ev in events:
            if ev["wall_start"] <= end_wall and ev["wall_end"] >= start_wall:
                return True
        return False

    def bucket(self, start_wall: float, end_wall: float) -> str:
        """Mutually exclusive label. A freeze hides a gap on the same hold."""
        if self._overlaps(self.freezes, start_wall, end_wall):
            return "freeze_hit"
        if self._overlaps(self.gaps, start_wall, end_wall):
            return "data_gap"
        return "clean"

    def snapshot(self) -> dict:
        return {
            "freezes": list(self.freezes),
            "gaps": list(self.gaps),
            "entries_paused": self.entries_paused(),
            "pending_flatten": self.pending_flatten,
            "freeze_detect_s": FREEZE_DETECT_S,
            "entry_pause_s": ENTRY_PAUSE_S,
            "flatten_freeze_s": FLATTEN_FREEZE_S,
            "ws_gap_s": WS_GAP_S,
        }
