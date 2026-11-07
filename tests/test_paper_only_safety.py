"""Offline tests for the paper-only comparison harness.

These tests do not open market feeds, do not load a key, and do not send
a transaction. The subprocess cases start a fresh interpreter so config.py
is imported only after PAPER_COMPARE_LOCK is set.
"""

from __future__ import annotations

import ast
import asyncio
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "paper_only"

from paper_only.book import CompareBook
from paper_only.costs import (
    ADVERSE_SLIPPAGE,
    FEE_RATE,
    FIXED_ENTRY_SOL,
    PRIORITY_FEE_SOL,
    buy_fill,
    sell_fill,
)
from paper_only.executor import ComparisonPaperExecutor
from paper_only.feedhealth import FLATTEN_FREEZE_S, FeedHealth
from paper_only.frozen import LOCKED_ENV_NAMES
from paper_only.net_guard import PaperSafetyError, inspect_call, install_network_guard
from paper_only.runner import assert_safe_state_dir
from paper_only.sizing import fixed_entry_size


def _run(coro):
    """Run a coroutine without leaving the process event loop closed.

    Other tests in this repo call asyncio.get_event_loop(). asyncio.run()
    clears that loop on 3.12 and those tests then fail.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def test_frozen_env_covers_every_config_knob():
    text = (ROOT / "config.py").read_text(encoding="utf-8")
    names = set(re.findall(
        r'_env_(?:bool|int|float|json)\s*\(\s*"([A-Z0-9_]+)"',
        text,
    ))
    missing = names - set(LOCKED_ENV_NAMES)
    assert not missing, f"config knobs not locked: {sorted(missing)}"


def test_buy_and_sell_use_comparison_costs():
    mid = 1e-8
    bought = buy_fill(mid)
    assert bought["notional_sol"] == FIXED_ENTRY_SOL
    assert bought["tokens"] == int(FIXED_ENTRY_SOL / (mid * (1 + ADVERSE_SLIPPAGE)))
    assert bought["fee_sol"] == pytest.approx(FIXED_ENTRY_SOL * FEE_RATE)
    assert bought["priority_sol"] == PRIORITY_FEE_SOL
    assert bought["cash_debit"] == pytest.approx(
        FIXED_ENTRY_SOL + bought["fee_sol"] + PRIORITY_FEE_SOL
    )
    sold = sell_fill(bought["tokens"], mid)
    gross = bought["tokens"] * mid * (1 - ADVERSE_SLIPPAGE)
    assert sold["sol_received"] == pytest.approx(gross * (1 - FEE_RATE) - PRIORITY_FEE_SOL)
    assert sold["sol_received"] < FIXED_ENTRY_SOL


class _Wallet:
    def __init__(self) -> None:
        self.balance = 1.0

    async def get_sol_balance(self) -> float:
        return self.balance

    def deduct(self, amount: float) -> None:
        self.balance -= amount

    def credit(self, amount: float) -> None:
        self.balance += amount


def test_executor_never_signs_and_debits_full_cost():
    wallet = _Wallet()
    exe = ComparisonPaperExecutor(wallet)
    token = {
        "v_sol_in_bonding": 30.0,
        "v_tokens_in_bonding": 1_000_000_000.0,
    }
    result = _run(exe.buy("MintPaperOnly111", 0.1, token=token))
    assert result["success"] is True
    assert result["venue"] == "paper"
    assert result["signature"].startswith("PAPER_")
    assert "keypair" not in result
    assert wallet.balance == pytest.approx(1.0 - result["cash_debit"])
    sold = _run(exe.sell("MintPaperOnly111", "100%", reason="stop_loss"))
    assert sold["success"] is True
    assert sold["signature"].startswith("PAPER_SELL_")
    assert sold["venue"] == "paper"
    assert wallet.balance == pytest.approx(1.0 - result["cash_debit"] + sold["sol_received"])


def test_executor_rejects_non_fixed_size():
    exe = ComparisonPaperExecutor(_Wallet())
    result = _run(exe.buy("MintPaperOnly111", 0.25, token={
        "v_sol_in_bonding": 30.0,
        "v_tokens_in_bonding": 1_000_000_000.0,
    }))
    assert result["success"] is False
    assert result["error"] == "non_fixed_size"


def test_fixed_size_gate_rejects_clipped_upstream_size():
    class _Risk:
        async def calculate_position_size(self, score, symbol=None):
            return 0.05, ""

    size, reason = _run(fixed_entry_size(_Risk(), 80, "AAA"))
    assert size == 0.0
    assert reason == "fixed_size_unavailable"


def test_fixed_size_gate_passes_exact_tenth():
    class _Risk:
        async def calculate_position_size(self, score, symbol=None):
            return 0.1, ""

    size, reason = _run(fixed_entry_size(_Risk(), 80, "AAA"))
    assert size == 0.1
    assert reason == ""


def test_freeze_pause_and_flatten_are_separate_from_clean_bucket(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    health = FeedHealth()
    assert health.observe_stall(4.9) is None
    small = health.observe_stall(6.0, wall_end=1_000.0)
    assert small is not None
    assert small["flatten"] is False
    assert health.entries_paused() is True
    assert health.consume_flatten() is False
    big = health.observe_stall(FLATTEN_FREEZE_S, wall_end=2_000.0)
    assert big["flatten"] is True
    assert health.consume_flatten() is True
    assert health.bucket(1_900.0, 2_000.0) == "freeze_hit"
    assert health.bucket(10.0, 20.0) == "clean"
    health.note_ws_message()
    health._last_ws -= 20
    gap = health.note_ws_message()
    assert gap is not None and gap["kind"] == "data_gap"
    book = CompareBook(health)
    book.on_open("M", {"sol_spent": 0.1, "fee_sol": 0.001, "priority_sol": 0.0005})
    tagged = book.tag_record({
        "mint": "M",
        "symbol": "M",
        "reason": "stop_loss",
        "entry_time": 1_950.0,
        "exit_time": 2_000.0,
        "sol_invested": 0.1,
        "sol_received": 0.08,
        "pnl_sol": -0.02,
        "partial": False,
        "score": 70,
    })
    assert tagged["bucket"] == "freeze_hit"
    assert tagged["cash_pnl_sol"] == pytest.approx(-0.02 - 0.0015)
    summary = (tmp_path / "logs" / "compare_buckets.json").read_text(encoding="utf-8")
    assert "freeze_hit" in summary
    assert "clean" in summary


def test_network_guard_blocks_send_and_allows_account_read():
    os.environ["PAPER_COMPARE_LOCK"] = "1"
    try:
        inspect_call("https://api.mainnet-beta.solana.com", {
            "json": {"jsonrpc": "2.0", "id": 1, "method": "getAccountInfo", "params": []},
        })
        with pytest.raises(PaperSafetyError):
            inspect_call("https://api.mainnet-beta.solana.com", {
                "json": {"jsonrpc": "2.0", "id": 1, "method": "sendTransaction", "params": []},
            })
        with pytest.raises(PaperSafetyError):
            inspect_call("https://pumpportal.fun/api/trade-local", {"json": {}})
        with pytest.raises(PaperSafetyError):
            inspect_call("https://ny.mainnet.block-engine.jito.wtf/api/v1/transactions", {"json": {}})
        install_network_guard()
        import aiohttp

        async def _attempt():
            session = aiohttp.ClientSession()
            try:
                await session._request(
                    "POST",
                    "https://api.mainnet-beta.solana.com",
                    json={"jsonrpc": "2.0", "method": "sendRawTransaction", "params": []},
                )
            finally:
                await session.close()

        with pytest.raises(PaperSafetyError):
            _run(_attempt())
    finally:
        os.environ.pop("PAPER_COMPARE_LOCK", None)


def test_state_dir_refuses_baseline_and_repo_root(tmp_path):
    with pytest.raises(RuntimeError):
        assert_safe_state_dir(ROOT, ROOT)
    baseline = tmp_path / "pumpfun-sniper"
    baseline.mkdir()
    with pytest.raises(RuntimeError):
        assert_safe_state_dir(baseline, ROOT)
    nested = tmp_path / "pumpfun-sniper" / "state"
    with pytest.raises(RuntimeError):
        assert_safe_state_dir(nested, ROOT)
    ok = tmp_path / "paper_compare_state"
    assert assert_safe_state_dir(ok, ROOT) == ok.resolve()


def test_harness_sources_do_not_import_signers():
    banned = {
        "trader.wallet",
        "trader.executor",
        "trader.pumpportal_executor",
        "trader.local_tx_builder",
        "solders.keypair",
    }
    # selfcheck imports the signer modules only to assert they raise.
    runtime = {
        "runner.py",
        "executor.py",
        "prices.py",
        "book.py",
        "sizing.py",
        "costs.py",
        "feedhealth.py",
        "__main__.py",
        "lock.py",
        "frozen.py",
        "net_guard.py",
    }
    for path in PAPER.glob("*.py"):
        if path.name not in runtime:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in banned:
                raise AssertionError(f"{path.name} imports {node.module}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in banned:
                        raise AssertionError(f"{path.name} imports {alias.name}")
        if path.name != "net_guard.py":
            text = path.read_text(encoding="utf-8")
            assert "sendTransaction" not in text
            assert "sendRawTransaction" not in text


def test_self_check_ignores_hostile_dotenv(tmp_path):
    (tmp_path / ".env").write_text(
        "\n".join([
            "PAPER_TRADING=false",
            "SOLANA_PRIVATE_KEY=this-is-not-a-wallet",
            "MAX_SOL_PER_TRADE=9",
            "MIN_BUY_SCORE=1",
            "AUTO_TUNE_ENABLED=true",
            "ADAPTIVE_SIZING_ENABLED=true",
            "RPC_URL=https://mainnet.helius-rpc.com/?api-key=secret",
            "HELIUS_API_KEY=secret",
            "TWITTER_BEARER_TOKEN=secret",
            "TELEGRAM_BOT_TOKEN=secret",
        ]),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(ROOT),
        "PAPER_TRADING": "false",
        "SOLANA_PRIVATE_KEY": "this-is-not-a-wallet",
        "MAX_SOL_PER_TRADE": "9",
        "MIN_BUY_SCORE": "1",
        "RPC_URL": "https://mainnet.helius-rpc.com/?api-key=secret",
    })
    env.pop("PAPER_COMPARE_LOCK", None)
    proc = subprocess.run(
        [sys.executable, "-m", "paper_only", "--self-check"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "paper-only self-check ok" in proc.stdout
    assert "this-is-not-a-wallet" not in proc.stdout


def test_missing_risk_reads_are_not_clean_entries(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    health = FeedHealth()
    book = CompareBook(health)
    from paper_only.risk_gate import entry_block_reason

    missing = {"mint": "MintUnread", "symbol": "UNREAD"}
    assert entry_block_reason(missing) == "holder_data_unavailable"
    book.note_blocked(missing, "holder_data_unavailable")
    ready = {"holder_check": "ok", "freeze_check": "safe"}
    assert entry_block_reason(ready) == ""
    text = (tmp_path / "logs" / "blocked_entries.jsonl").read_text(encoding="utf-8")
    assert "holder_data_unavailable" in text
    assert "counts_as_trade" in text
    summary = (tmp_path / "logs" / "compare_buckets.json").read_text(encoding="utf-8")
    assert "blocked_missing_risk" in summary
    assert '"clean"' in summary


def test_wall_jump_is_a_freeze_and_not_a_feed_gap():
    health = FeedHealth()
    health._last_wall = time.time() - 631
    health._last_beat = time.monotonic() - 1.0
    rec = health.heartbeat()
    assert rec is not None
    assert rec["clock"] == "wall"
    assert rec["stall_s"] >= 300
    assert rec["flatten"] is True
    assert health.consume_flatten() is True
    health.note_ws_message()
    assert health.note_ws_message() is None


def test_refresh_age_does_not_invent_market_fields():
    from paper_only.scoring import refresh_score_age

    token = {"created_ts": 1_000.0, "age_minutes": 0, "bonding_curve_pct": 29.41}
    age = refresh_score_age(token, now=1_000.0 + 120)
    assert age == pytest.approx(2.0)
    assert token["age_source"] == "wall_since_create"
    assert token["bonding_curve_pct"] == 29.41
    assert "price_change_5m" not in token
    assert "dex_pair_address" not in token
    assert refresh_score_age({"age_minutes": 0}, now=5) is None


def test_rescore_only_when_data_can_still_arrive():
    from paper_only.scoring import should_rescore

    low = {"reject_reason": "score_40"}
    unread = {"reject_reason": "holder_data_unavailable"}
    permanent = {"reject_reason": "big_init_buy_4.94sol"}
    bought = {"reject_reason": "score_70", "paper_buy_queued": True}
    assert should_rescore(low, 1, elapsed_s=20) is True
    assert should_rescore(unread, 2, elapsed_s=40) is True
    assert should_rescore(permanent, 1, elapsed_s=20) is False
    assert should_rescore(bought, 1, elapsed_s=20) is False
    assert should_rescore(low, 8, elapsed_s=20) is False
    assert should_rescore(low, 1, elapsed_s=601) is False


def test_diagnostics_mark_missing_inputs_and_not_reached_risk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from paper_only.scoring import input_availability, write_diagnostic

    token = {
        "mint": "MintDiag",
        "symbol": "DIAG",
        "score": 40,
        "raw_score": 40,
        "reject_reason": "score_40",
        "age_source": "wall_since_create",
        "age_minutes": 0.25,
        "score_breakdown": {
            "creator": 22,
            "bonding_curve": 8,
            "community": 5,
            "price_momentum": 5,
        },
    }
    avail = input_availability(token)
    assert avail["dex"] == "unavailable"
    assert avail["price_change_5m"] == "default_zero"
    assert avail["pumpfun_tracker"] == "unavailable"
    assert avail["holder_check"] == "not_reached"
    assert avail["freeze_check"] == "not_reached"
    write_diagnostic(token, attempt=1)
    text = (tmp_path / "logs" / "score_diagnostics.jsonl").read_text(encoding="utf-8")
    assert "score_40" in text
    assert "unavailable" in text
    assert "not_reached" in text


def test_tracker_deadline_clock_under_lock(monkeypatch):
    from detector.pumpfun_tracker import deadline_clock

    monkeypatch.delenv("PAPER_COMPARE_LOCK", raising=False)
    assert deadline_clock() is time.time
    monkeypatch.setenv("PAPER_COMPARE_LOCK", "1")
    assert deadline_clock() is time.monotonic


def test_holder_read_failure_returns_none():
    from detector.holder_filter import get_top10_concentration

    class _Boom:
        def post(self, *args, **kwargs):
            raise TimeoutError("rpc down")

    assert _run(get_top10_concentration(_Boom(), "MintUnreadRpc")) is None


def test_holder_read_success_returns_pct():
    from detector.holder_filter import get_top10_concentration

    class _Resp:
        def __init__(self, payload):
            self.payload = payload

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def json(self):
            return self.payload

    class _Session:
        def __init__(self):
            self.calls = 0

        def post(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return _Resp({"result": {"value": [
                    {"amount": "250"},
                    {"amount": "750"},
                ]}})
            return _Resp({"result": {"value": {"amount": "1000"}}})

    pct = _run(get_top10_concentration(_Session(), "MintOkConcentration"))
    assert pct == pytest.approx(100.0)


@pytest.mark.skipif(not (ROOT / "main.py").exists(), reason="main.py is not in the inert package")
def test_main_refuses_to_run_under_the_lock():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["PAPER_COMPARE_LOCK"] = "1"
    env["PAPER_TRADING"] = "true"
    env["SOLANA_PRIVATE_KEY"] = ""
    proc = subprocess.run(
        [sys.executable, "-c", "import asyncio\nfrom main import main\nasyncio.run(main())\n"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 3, proc.stdout + proc.stderr


def test_import_blocker_refuses_signer_modules():
    code = (
        "import os\n"
        "os.environ['PAPER_COMPARE_LOCK']='1'\n"
        "from paper_only.net_guard import install_import_blocker, PaperSafetyError\n"
        "install_import_blocker()\n"
        "try:\n"
        "    import trader.executor\n"
        "except PaperSafetyError as exc:\n"
        "    assert 'trader.executor' in str(exc)\n"
        "else:\n"
        "    raise SystemExit('signer module imported')\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env.pop("PAPER_COMPARE_LOCK", None)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
