"""Offline checks. No network, no wallet material, no transaction."""

from __future__ import annotations


def run_self_check() -> int:
    import config
    from paper_only.costs import FIXED_ENTRY_SOL, buy_fill
    from paper_only.frozen import PUBLIC_RPC_PRIMARY

    assert config.PAPER_TRADING is True
    assert config.PRIVATE_KEY == ""
    assert abs(config.MAX_SOL_PER_TRADE - FIXED_ENTRY_SOL) < 1e-12
    assert config.ADAPTIVE_SIZING_ENABLED is False
    assert config.AUTO_TUNE_ENABLED is False
    assert config.MIN_BUY_SCORE == 60
    assert config.MAX_OPEN_POSITIONS == 3
    assert config.RPC_URL == PUBLIC_RPC_PRIMARY
    assert config.HELIUS_API_KEY == ""
    assert config.TWITTER_BEARER_TOKEN == ""
    assert buy_fill(1e-8)["tokens"] > 0

    from trader.wallet import SolanaWallet

    try:
        SolanaWallet()
    except RuntimeError as exc:
        if "PAPER_COMPARE_LOCK" not in str(exc):
            raise
    else:
        raise RuntimeError("SolanaWallet constructed under the paper lock")

    from trader.local_tx_builder import build_buy_tx_bytes

    try:
        build_buy_tx_bytes(  # type: ignore[arg-type]
            user=None, mint=None, sol_amount_lamports=1, v_sol_reserves=1,
            v_token_reserves=1, slippage_bps=1, cu_limit=1,
            cu_price_micro_lamports=1, recent_blockhash=None,
        )
    except RuntimeError as exc:
        if "PAPER_COMPARE_LOCK" not in str(exc):
            raise
    else:
        raise RuntimeError("build_buy_tx_bytes ran under the paper lock")

    print("paper-only self-check ok")
    print("mode: upstream decision modules, isolated")
    print("no wallet loaded, no transaction built, no network called")
    return 0
