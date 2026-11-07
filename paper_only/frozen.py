"""Frozen thresholds for the paper comparison.

Values are the config.py defaults at source commit
9290bc9fb72a49f2955bada2ad3ff4b0d0f1df48, plus the documented comparison
overrides (fixed 0.1 SOL, no adaptive compounding, auto-tune off).

The README "strategy at a glance" table does not match these defaults.
This file follows the code, not that table.
"""

from __future__ import annotations

SOURCE_COMMIT = "9290bc9fb72a49f2955bada2ad3ff4b0d0f1df48"
SOURCE_REPO = "https://github.com/Jkurre697/solana-pumpfun-bot"
UPSTREAM_REPO = "https://github.com/DeeKalshiWay/solana-pumpfun-bot"

# Public read-only Solana HTTP RPC. No API key.
PUBLIC_RPC_PRIMARY = "https://api.mainnet-beta.solana.com"
PUBLIC_RPC_BACKUP = "https://solana-rpc.publicnode.com"

# Upstream code defaults. Applied even if the shell or a .env disagrees.
FROZEN_UPSTREAM: dict[str, str] = {
    "PAPER_STARTING_SOL": "1.0",
    "PAPER_TIME_EXIT_MIN": "10",
    "USE_LOCAL_TX_BUILD": "false",
    "COMPUTE_UNIT_LIMIT": "200000",
    "COMPUTE_UNIT_PRICE_MICROLAMPORTS": "300000",
    "MIN_BUY_SCORE": "60",
    "MIN_BONDING_CURVE_PCT": "30.0",
    "MAX_BONDING_CURVE_PCT": "80.0",
    "BUY_COOLDOWN_SECONDS": "15",
    "MAX_INITIAL_BUY_SOL": "3.5",
    "CREATOR_TRACKING_ENABLED": "true",
    "CREATOR_TOP_N": "50",
    "CREATOR_MIN_LAUNCHES": "2",
    "MAX_TOTAL_EXPOSURE_SOL": "0.50",
    "MAX_OPEN_POSITIONS": "3",
    "ADAPTIVE_LOOKBACK": "20",
    "ADAPTIVE_HOT_WR": "0.55",
    "ADAPTIVE_COLD_WR": "0.30",
    "TAKE_PROFIT_LEVELS": (
        '[{"gain_pct": 50, "sell_pct": 25}, '
        '{"gain_pct": 100, "sell_pct": 25}, '
        '{"gain_pct": 200, "sell_pct": 25}]'
    ),
    "TRAILING_STOP_ENABLED": "true",
    "TRAILING_STOP_MIN_PROFIT": "20.0",
    "TRAILING_STOP_PCT": "15.0",
    "TRAILING_STOP_MOONSHOT_PCT": "25.0",
    "TRAILING_STOP_MOONSHOT_TRIGGER": "100.0",
    "STOP_LOSS_PCT": "15.0",
    "EMERGENCY_STOP_DRAWDOWN_PCT": "25.0",
    "TIME_EXIT_MINUTES": "5",
    "PANIC_STOP_LOSS_PCT": "25.0",
    "MAX_SYMBOL_LIFETIME_DEPLOY_PCT": "10.0",
    "REGIME_FILTER_ENABLED": "true",
    "REGIME_PAUSE_RATIO": "0.5",
    "REGIME_MIN_HOURS": "6",
    "EARLY_RUG_PCT": "5.0",
    "EARLY_RUG_WINDOW_SEC": "60",
    "SMART_CALLER_MIN": "20",
    "FUSION_ENABLED": "true",
    "FUSION_MAX_BONUS": "15",
    "FUSION_MAX_PENALTY": "10",
    "RUG_MATCH_MIN_RUGS": "1",
    "RUG_MAX_PENALTY": "50",
    "RUG_HARD_REJECT_MATCHES": "3",
    "AUTO_TUNE_OFFSET_MIN": "-3",
    "AUTO_TUNE_OFFSET_MAX": "5",
    "NO_MOVEMENT_EXIT_SECONDS": "90",
    "NO_MOVEMENT_BAND_PCT": "3.0",
    "LOSS_STREAK_LIMIT": "5",
    "LOSS_STREAK_PAUSE_MIN": "15",
    "DAILY_LOSS_LIMIT_PCT": "20.0",
    "DAILY_PROFIT_LOCK_PCT": "9999.0",
    "MOMENTUM_STALL_ENABLED": "true",
    "MOMENTUM_STALL_PCT_BAND": "5.0",
    "MOMENTUM_STALL_WINDOW_SEC": "60",
    "MOMENTUM_STALL_MIN_PROFIT": "5.0",
    "EXIT_LATENCY_ENABLED": "true",
    "EXIT_LATENCY_P50_S": "0.8",
    "EXIT_LATENCY_P99_S": "3.0",
    "STAMPEDE_MULT_STALL": "5.0",
    "SLIPPAGE_BPS": "1500",
    "BUY_SLIPPAGE_BPS": "1500",
    "SELL_SLIPPAGE_BPS": "4000",
    "PRIORITY_FEE_SOL": "0.001",
    "SELL_PRIORITY_FEE_SOL": "0.005",
}

# Documented deltas from upstream defaults. Required for this comparison.
COMPARISON_OVERRIDES: dict[str, str] = {
    "PAPER_TRADING": "true",
    "MAX_SOL_PER_TRADE": "0.1",
    "MAX_POSITION_PCT": "1",
    "ADAPTIVE_SIZING_ENABLED": "false",
    "ADAPTIVE_HOT_MULT": "1",
    "ADAPTIVE_COLD_MULT": "1",
    "ADAPTIVE_HARD_CAP_MULT": "1",
    "AUTO_TUNE_ENABLED": "false",
    "REALISTIC_PAPER_SIM": "0",
    "USE_LOCAL_TX_BUILD": "false",
    "RPC_URL": PUBLIC_RPC_PRIMARY,
    "EXTRA_RPC_URLS": "",
    "JITO_REGION": "",
}

# Cleared so this process cannot authenticate a paid API or send a message.
BLANKED_SECRETS: dict[str, str] = {
    "SOLANA_PRIVATE_KEY": "",
    "HELIUS_API_KEY": "",
    "BIRDEYE_API_KEY": "",
    "TWITTER_BEARER_TOKEN": "",
    "X_BEARER_TOKEN": "",
    "TELEGRAM_API_ID": "0",
    "TELEGRAM_API_HASH": "",
    "TELEGRAM_PHONE": "",
    "TELEGRAM_CHANNELS": "",
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_OWNER_CHAT_ID": "",
    "TELEGRAM_CHAT_ID": "",
    "TELEGRAM_RELAY_CHAT_ID": "",
    "SMTP_HOST": "",
    "SMTP_USER": "",
    "SMTP_PASSWORD": "",
    "REPORT_EMAIL_TO": "",
    "REPORT_EMAIL_FROM": "",
    "DASHBOARD_AUTH_USER": "",
    "DASHBOARD_AUTH_PASS": "",
    "RELAY_SECRET": "",
    "SYNTHETIC_INJECT": "",
    "GRAD_ALERTS": "0",
}

# config._env_* names the lock must set. The test parses config.py for these.
LOCKED_ENV_NAMES: frozenset[str] = frozenset(
    set(FROZEN_UPSTREAM) | set(COMPARISON_OVERRIDES)
)
