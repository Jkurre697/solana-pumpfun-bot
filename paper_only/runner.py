"""Run upstream scoring and risk code under the paper lock.

What this is
------------
SignalScorer and RiskManager from this repository, at the pinned commit,
with the public PumpPortal new-token stream and the public read-only price
readers. Exits are the upstream risk manager's. Fills are ComparisonPaperExecutor.

What this is not
----------------
It is not `python main.py`. main.py can construct a live signer when
PAPER_TRADING is false, and it starts a dashboard that can force-sell.
It is not tools/graduation_sniper.py, which is a different paper strategy
with a 0.25 SOL size. It is not a reimplementation of the scorer. It is
not evidence of profit.

State is written under the dedicated state directory after chdir, in
relative logs/. That directory must not be the baseline bot folder.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

from paper_only.book import CompareBook
from paper_only.feedhealth import FeedHealth
from paper_only.frozen import (
    PUBLIC_RPC_BACKUP,
    PUBLIC_RPC_PRIMARY,
    SOURCE_COMMIT,
    SOURCE_REPO,
    UPSTREAM_REPO,
)
from paper_only.net_guard import install_import_blocker, install_network_guard
from paper_only.risk_gate import entry_block_reason
from paper_only.sizing import fixed_entry_size

_BASELINE_NAME = "pumpfun-sniper"


def assert_safe_state_dir(path: Path, repo: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo_resolved = repo.resolve()
    if resolved == repo_resolved:
        raise RuntimeError("paper state directory must not be the repository root")
    for part in resolved.parts:
        if part.lower() == _BASELINE_NAME:
            raise RuntimeError(
                "refusing to use a pumpfun-sniper path. "
                "The baseline bot stays untouched."
            )
    if (resolved / ".env").exists():
        raise RuntimeError("refusing a state directory that contains .env")
    return resolved


def _write_pin(repo: Path) -> None:
    pin = {
        "source_commit": SOURCE_COMMIT,
        "source_repo": SOURCE_REPO,
        "upstream_repo": UPSTREAM_REPO,
        "license": "MIT; see LICENSE at the repository root. Copyright (c) 2026.",
        "mode": "upstream decision modules, isolated",
        "not": [
            "unmodified python main.py",
            "tools/graduation_sniper.py",
            "a port that reimplements the scorer",
            "a profitability result",
        ],
        "entry_sol": 0.1,
        "compounding": False,
        "costs": {
            "curve_principal_sol": 0.1,
            "fee_rate_per_side": 0.01,
            "adverse_slippage_per_side": 0.02,
            "priority_sol_per_tx": 0.0005,
            "entry_cash_debit_sol": 0.1015,
            "fee_accounting": (
                "0.1 SOL is curve principal. Entry cash is 0.1 + 0.001 fee "
                "+ 0.0005 priority = 0.1015 SOL. This is not a 0.1 SOL total "
                "input, and fills are not claimed to match the baseline."
            ),
        },
        "feeds": {
            "launches": "wss://pumpportal.fun/api/data subscribeNewToken (public, no key)",
            "prices": [
                "getAccountInfo on the pump.fun bonding-curve PDA",
                "https://api.dexscreener.com (fallback)",
            ],
            "rpc_primary": PUBLIC_RPC_PRIMARY,
            "rpc_backup": PUBLIC_RPC_BACKUP,
            "not_used": [
                "Helius",
                "Birdeye",
                "Jupiter swap or quote",
                "Twitter/X",
                "Telegram",
                "logsSubscribe (that is the baseline feed, not this one)",
            ],
        },
        "fidelity_gaps": [
            "README strategy table disagrees with config.py defaults; frozen values are the code defaults.",
            "Auto-tune is forced off. Adaptive size is forced off. Max position percent is 1 so the 0.1 entry is not clipped to 5% of the 1 SOL book.",
            "Max open positions stays at the upstream default of 3, not the baseline's 4.",
            "Symbol lifetime cap stays 10% of the 1.0 SOL starting book, so a second 0.1 entry in the same symbol is refused.",
            "Upstream realistic paper sim (MEV tax, 5% fail rate, size slippage, 0.001/0.005 priority caps) is not used.",
            "Exit-latency and stampede sampling from trader.paper_executor are not used.",
            "Jupiter quotes are not used after migration. DexScreener is the fallback.",
            "Holder concentration and freeze authority must both be read successfully or the entry is blocked and logged under blocked_missing_risk, not as a clean trade. Upstream without this lock still fail-opens those reads.",
            "Bundle detection still treats a quiet trade window as not bundled. If PumpPortal omits trade events, that classification is incomplete and is not a second strategy.",
            "Twitter, Telegram, email, the web dashboard, and the graduation sniper are not started.",
            "Buy cooldown remains 15 seconds, from upstream config.",
        ],
    }
    try:
        import subprocess
        rev = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if rev.returncode == 0:
            pin["git_head"] = rev.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pin["git_head"] = None
    os.makedirs("logs", exist_ok=True)
    with open("logs/PAPER_COMPARE_PIN.json", "w", encoding="utf-8") as handle:
        json.dump(pin, handle, indent=2)
    with open("PAPER_COMPARE_PIN.json", "w", encoding="utf-8") as handle:
        json.dump(pin, handle, indent=2)


def _acquire_pid() -> None:
    os.makedirs("logs", exist_ok=True)
    path = "logs/paper_compare.pid"
    if os.path.exists(path):
        try:
            old = int(Path(path).read_text(encoding="utf-8").strip())
        except ValueError:
            old = None
        if old and old != os.getpid():
            try:
                os.kill(old, 0)
            except OSError:
                old = None
            else:
                raise SystemExit(f"paper comparison already running (pid {old})")
    Path(path).write_text(str(os.getpid()), encoding="utf-8")


async def _trade_loop(trade_queue, executor, risk, health: FeedHealth, book: CompareBook) -> None:
    from config import CREATOR_BLACKLIST

    while True:
        try:
            token = await asyncio.wait_for(trade_queue.get(), timeout=1.0)
        except TimeoutError:
            continue
        if risk.emergency_stop_active:
            continue
        if health.entries_paused():
            continue
        mint = token.get("mint", "")
        symbol = token.get("symbol", "???")
        creator = token.get("creator", "")
        if creator and creator in CREATOR_BLACKLIST:
            continue
        blocked = entry_block_reason(token)
        if blocked:
            book.note_blocked(token, blocked)
            continue
        score = int(token.get("score") or 0)
        sol_amount, _reason = await fixed_entry_size(risk, score, symbol)
        if sol_amount <= 0:
            continue
        result = await executor.buy(mint, sol_amount, token=token)
        if result.get("success") and result.get("tokens_expected", 0) > 0:
            risk.open_position(token, result)
            book.on_open(mint, result)


async def _heartbeat(health: FeedHealth, risk, book: CompareBook) -> None:
    while True:
        await asyncio.sleep(1.0)
        health.heartbeat()
        if health.consume_flatten():
            for mint in list(risk.positions):
                await risk._force_sell(mint, "freeze_flatten")
        book.write_health()


async def _prices(risk, executor) -> None:
    import aiohttp

    from paper_only.prices import read_price

    async with aiohttp.ClientSession() as session:
        while True:
            mints = list(risk.positions.keys())
            if mints:
                marks = await asyncio.gather(
                    *[read_price(session, mint) for mint in mints],
                    return_exceptions=True,
                )
                for mint, mark in zip(mints, marks, strict=True):
                    if isinstance(mark, (int, float)) and mark > 0:
                        risk.update_price(mint, mark)
                        executor.update_price(mint, mark)
            await asyncio.sleep(1.5)


def _make_risk_class(risk_manager_cls, book: CompareBook):
    class CompareRisk(risk_manager_cls):
        def close_position(self, mint: str, sell_result: dict):
            before = len(self.closed_trades)
            super().close_position(mint, sell_result)
            if len(self.closed_trades) > before:
                book.tag_record(self.closed_trades[-1])

        def _record_partial_close(self, mint, pos, sell_fraction, sell_result, level_id):
            before = len(self.closed_trades)
            super()._record_partial_close(mint, pos, sell_fraction, sell_result, level_id)
            if len(self.closed_trades) > before:
                book.tag_record(self.closed_trades[-1])

    return CompareRisk


async def launch(state_dir: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    state = assert_safe_state_dir(state_dir, repo)
    state.mkdir(parents=True, exist_ok=True)
    os.chdir(state)
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))

    install_network_guard()
    install_import_blocker()
    _write_pin(repo)
    _acquire_pid()

    from loguru import logger

    from analyzer.regime_filter import regime_filter
    from analyzer.signal_scorer import SignalScorer
    from config import (
        MAX_OPEN_POSITIONS,
        MAX_SOL_PER_TRADE,
        MIN_BUY_SCORE,
        PAPER_STARTING_SOL,
        PAPER_TRADING,
    )
    from detector.pumpfun_monitor import PumpFunMonitor
    from detector.pumpfun_tracker import PumpFunTracker
    from detector.wallet_intel import wallet_intel
    from detector.whale_tracker import whale_tracker
    from paper_only.executor import ComparisonPaperExecutor
    from paper_only.logging_setup import setup_logging
    from risk.manager import RiskManager
    from trader.paper_wallet import PaperWallet

    if not PAPER_TRADING:
        raise RuntimeError("paper lock failed: PAPER_TRADING is false")
    if abs(MAX_SOL_PER_TRADE - 0.1) > 1e-9:
        raise RuntimeError(f"paper lock failed: MAX_SOL_PER_TRADE={MAX_SOL_PER_TRADE}")

    setup_logging()
    logger.warning(
        "PAPER COMPARE starting. Upstream SignalScorer + RiskManager, "
        f"fixed 0.1 SOL, commit pin {SOURCE_COMMIT}. Not a profit claim. "
        f"min_score={MIN_BUY_SCORE} max_positions={MAX_OPEN_POSITIONS} "
        f"starting_book={PAPER_STARTING_SOL}."
    )

    health = FeedHealth()
    book = CompareBook(health)
    book.write_summary()

    class _ObservedMonitor(PumpFunMonitor):
        async def _handle_message(self, raw):
            health.note_ws_message()
            await super()._handle_message(raw)

    raw_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
    trade_queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    wallet = PaperWallet(PAPER_STARTING_SOL)
    executor = ComparisonPaperExecutor(wallet)
    compare_cls = _make_risk_class(RiskManager, book)
    risk = compare_cls(wallet, executor)
    await risk.initialize()
    scorer = SignalScorer(raw_queue, trade_queue, executor=executor)
    monitor = _ObservedMonitor(raw_queue)
    tracker = PumpFunTracker(monitor=monitor)
    wallet_intel.attach(monitor)
    whale_tracker.attach(monitor)
    regime_filter.attach(monitor)

    shutdown = asyncio.Event()

    def _stop() -> None:
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    tasks = [
        asyncio.create_task(monitor.run(), name="pumpfun"),
        asyncio.create_task(tracker.run(), name="pumpfun_tracker"),
        asyncio.create_task(wallet_intel.run(), name="wallet_intel"),
        asyncio.create_task(scorer.start(), name="scorer"),
        asyncio.create_task(_trade_loop(trade_queue, executor, risk, health, book), name="trade"),
        asyncio.create_task(risk.run_monitor_loop(), name="risk"),
        asyncio.create_task(_prices(risk, executor), name="prices"),
        asyncio.create_task(_heartbeat(health, risk, book), name="heartbeat"),
    ]
    await shutdown.wait()
    monitor.stop()
    tracker.stop()
    wallet_intel.stop()
    risk.stop()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    book.write_health()
    book.write_summary()
    logger.warning("PAPER COMPARE stopped. Buckets are in logs/compare_buckets.json.")
