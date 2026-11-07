# Paper-only comparison harness

This directory is an isolated way to exercise the **upstream decision
modules** in this repository (`SignalScorer` and `RiskManager`) with
fixed 0.1 SOL paper entries. It is not `python main.py`, it is not
`tools/graduation_sniper.py`, and it is not a claim that the strategy
makes money.

The MIT license at the repository root applies. Copyright (c) 2026.
Upstream project: https://github.com/DeeKalshiWay/solana-pumpfun-bot
This fork: https://github.com/Jkurre697/solana-pumpfun-bot

Pinned review commit for the strategy code this harness was written
against:

```
9290bc9fb72a49f2955bada2ad3ff4b0d0f1df48
```

`logs/PAPER_COMPARE_PIN.json` records the git HEAD actually launched.

## Do not run these

They were reviewed and left unused. Several can install services, read
a private key, or submit transactions:

- `python main.py`
- `deploy/install.sh` and `deploy/pump_bot.service`
- `Dockerfile`, `docker compose`
- `make-dashboard.sh` (also documents a `curl | bash` installer)
- `install_*.ps1`, `run_*.ps1`, `start_bot.bat`, `open_firewall.ps1`
- `tools/graduation_sniper.py` and `tools/preflight.py`
- `tools/control_bot.py`, `tools/twitter_relay.py`

Do not point `--state` at a `pumpfun-sniper` directory. That baseline
bot is separate and must stay untouched.

## What actually runs

`python -m paper_only` imports the repository's scorer and risk manager
after a lock is installed:

- `PAPER_TRADING` is forced on.
- `python-dotenv` is not loaded, so a nearby `.env` cannot flip the bot
  live or supply `SOLANA_PRIVATE_KEY`.
- `SolanaWallet`, `TradeExecutor`, `PumpPortalExecutor`, and the local
  transaction builders raise if constructed.
- HTTP calls whose JSON-RPC method submits a transaction are rejected.
- Telegram and email sends return immediately.
- Credentials for Helius, Birdeye, Twitter/X, Telegram, and SMTP are
  cleared in the process environment.

Fills are simulated in `paper_only/costs.py`. Nothing is signed.

### Fixed size

Every accepted entry is exactly **0.1 SOL** of curve notional. Adaptive
sizing is off, so a winning book does not increase the next entry. If
the upstream sizer would have used any other size, the harness skips
the trade instead of taking a partial.

Two upstream limits still apply and are frozen:

- At most **3** open positions (`MAX_OPEN_POSITIONS`), not 4.
- A symbol may receive only **10% of the 1.0 SOL starting book** over
  the run, which is 0.1 SOL. A second 0.1 entry in the same symbol name
  is refused. That is the upstream concentration cap, not a new rule.

`MAX_POSITION_PCT` is set to 1 so the upstream 5% of-wallet clip does
not shrink 0.1 SOL down to 0.05 SOL. That is a comparison override.
It is recorded in `paper_only/frozen.py`.

### Costs

Independent of `trader/paper_executor.py`:

| Item | Value |
|---|---|
| Entry notional | 0.1 SOL |
| Fee | 1% of notional on the buy, 1% of gross proceeds on the sell |
| Adverse slippage | 2% worse than mid, each side |
| Priority | 0.0005 SOL per transaction |

The buy fee and buy priority are **extra cash debits**. They are not
subtracted from the 0.1 before the curve fill. `RiskManager` pnl does
not include those entry debits. `logs/compare_trades.jsonl` stores both
`risk_pnl_sol` and `cash_pnl_sol` (risk pnl minus the allocated entry
fee and priority).

Upstream's own paper simulator is different: size-based slippage, an
MEV add-on, a 5% random failure, and priority caps of 0.001 SOL on
buys and 0.005 SOL on sells. This harness does not use that simulator.
Matching numbers to the README's paper curve would be a false claim.

### Frozen rules versus the README table

`config.py` at the pinned commit is what the scorer and risk manager
execute. The README "strategy at a glance" table does not match it.
Examples: the code take-profit ladder is +50/100/200% selling 25% each,
the stop is 15%, and the time exit is 5 minutes. The README table says
+75/300/800%, a 10% stop, and a 4 minute time exit. Thresholds are
frozen from the code. Auto-tune is forced off so the score floor stays
at 60.

### Feeds

No API key is required.

- Launches: public PumpPortal WebSocket `wss://pumpportal.fun/api/data`,
  method `subscribeNewToken`. This is not Solana `logsSubscribe`.
- Prices: `getAccountInfo` on the pump.fun bonding-curve account, then
  DexScreener if the curve account is gone.
- RPC: `https://api.mainnet-beta.solana.com`, then
  `https://solana-rpc.publicnode.com` for that account read only.

Not called: Helius, Birdeye, Jupiter, Twitter/X, Telegram, the web
dashboard, the graduation sniper.

Public endpoints rate-limit and disconnect. PumpPortal answers 403
when it rejects the client. The holder-concentration check fails open
on RPC errors, which is existing scorer behavior, so a rate limit can
let a trade through that a successful read would have blocked. Expect
gaps. They are not evidence of edge.

### Freezes and gaps

A heartbeat that wakes more than 5 seconds late is a host freeze. New
entries pause for 90 seconds. A single stall of at least 300 seconds
flattens open positions. Silence of at least 15 seconds on the
PumpPortal stream is a data gap. Closed legs are labeled `clean`,
`freeze_hit`, or `data_gap` in `logs/compare_buckets.json`. Those
buckets are separate on purpose. Do not add them into one profit number.

The 5 second detection floor is a harness parameter. The 90 second
pause and 300 second flatten match the comparison brief. They are not
rules inside `RiskManager`.

## Setup

From a clean checkout of this fork, after you have read
`artifacts/SECURITY_REVIEW.md`:

```bash
grep -v '^playwright' requirements.txt | python3 -m pip install -r /dev/stdin
python3 -m pip install pytest pytest-asyncio
python3 -m pytest tests/test_paper_only_safety.py
python3 -m paper_only --self-check
```

`playwright` is listed in `requirements.txt` and is not imported.
Leave it out. Do not run `deploy/install.sh`. `requirements-dev.txt`
pulls `requirements.txt` unchanged, including playwright, so prefer
the `grep` line above.

`--self-check` does not open a socket and does not accept a private key.
A `.env` that sets `PAPER_TRADING=false` must not change the result.

## Launch

Only after `--self-check` prints `paper-only self-check ok`:

```bash
python3 -m paper_only
```

State goes to `./paper_compare_state/` under the repository. That
folder is gitignored. Logs:

- `paper_compare_state/logs/PAPER_COMPARE_PIN.json`
- `paper_compare_state/logs/compare_trades.jsonl`
- `paper_compare_state/logs/compare_buckets.json`
- `paper_compare_state/logs/feed_health.json`
- `paper_compare_state/logs/pump_bot.log` (upstream logger, this state dir only)

Stop with Ctrl-C. The process does not install a service and does not
restart itself.

Optional state directory, still not a `pumpfun-sniper` path and still
not a folder that contains `.env`:

```bash
python3 -m paper_only --state /path/to/some-other-empty-dir
```

## How to read a result

A finished run is a sample of this scorer and this risk manager on
whatever the public feeds delivered, with the cost model above and
with freeze and gap legs split out. It does not validate the README
paper curve, the graduation-sniper notes, or live trading. Upstream's
own README says paper pnl was concentrated in a handful of tickers.
Treat a new run the same way: look at concentration before looking at
a total.
