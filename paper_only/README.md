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

### Costs (not the baseline's 0.1 SOL total input)

Independent of `trader/paper_executor.py`. Fills are not claimed to
match the baseline bot.

| Item | This harness | Baseline this is compared against |
|---|---|---|
| Curve principal | 0.1 SOL | described as 0.1 SOL total input |
| Entry cash out of the paper wallet | **0.1015 SOL** = 0.1 + 1% fee (0.001) + 0.0005 priority | 0.1 SOL all-in, fees inside that 0.1 |
| Adverse slippage | 2% worse than mid, each side | 2% worse than mid, each side |
| Sell | gross after 2% slippage, minus 1% of that gross, minus 0.0005 | 1% and 2% and 0.0005, accounted inside the baseline's own code |

`RiskManager` pnl uses curve principal versus sell proceeds. It does
not subtract the 0.001 + 0.0005 entry extras. `logs/compare_trades.jsonl`
stores `risk_pnl_sol` and `cash_pnl_sol` (risk pnl minus those entry
extras, allocated across partial sells).

Upstream's own paper simulator is different again: size-based slippage,
an MEV add-on, a 5% random failure, and priority caps of 0.001 SOL on
buys and 0.005 SOL on sells. This harness does not use that simulator.

### Missing holder and freeze data

Upstream, with the lock unset, treats a failed top-10 holder read as 0%
and a failed freeze-authority read as safe. Those would be normal buys
and could close in the clean bucket.

This process sets `PAPER_COMPARE_LOCK` before scoring. An entry is
opened only when `holder_check` is `ok` and `freeze_check` is `safe`.
A timeout, an RPC error, an empty holder list, or an account that is
not visible yet is refused. The refusal is appended to
`logs/blocked_entries.jsonl` and counted under `blocked_missing_risk`
in `logs/compare_buckets.json`. That counter is not a trade and is not
part of clean pnl.

Dex enrichment and the bundle window can still run without those
fields. A quiet trade subscription can look "not bundled". That
approximation is disclosed here. It does not turn the run into a
different strategy, and it does not mark those names as validated clean
when the holder or freeze read itself failed.

### What the no-trade fix changes, and what it does not

The score threshold stays 60. The four-factor math is the upstream
function. A create event is still scored from its launch snapshot, which
by itself tops out below 60 for a normal virtual curve near 29% with no
DexScreener pair and no tracker replies. That rejection is the strategy.

Three data-flow bugs were hiding whether a later real input could pass
the same rules:

- `age_minutes` stayed 0, so the existing DexScreener call (age over
  0.5 minutes) never ran and the fresh-token score floors never expired.
  Age is now wall time since the create event. Curve percent and market
  cap stay the launch snapshot. Missing dex or tracker fields stay at
  the scorer's defaults and are logged as unavailable, not filled in.
- A below-threshold or unread-risk result is rescored up to 8 times
  across 10 minutes. Permanent rejects (blacklist, missing symbol, big
  initial buy, a freeze authority that was actually set, holder
  concentration over the limit) are not retried. The holder and freeze
  gates still fail closed on every pass.
- A wall-clock jump that monotonic time does not include is recorded as
  a `clock=wall` freeze and can pause entries or flatten. Feed-silence
  gaps stay on the monotonic clock. This does not stop the host from
  suspending.

Each pass appends `logs/score_diagnostics.jsonl` and a `[SCORE PARTS]`
line with the four factors and whether dex, the pump.fun tracker, the
holder read, and the freeze read were present, defaulted, or not reached.

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

## Install on the parent computer without cloning

Use the archive `artifacts/paper-comparison-runtime.tar.gz` from this
review. Do not clone the git repo for this comparison. Do not copy it
onto the baseline bot. Nothing here installs systemd, Task Scheduler,
or a restart loop.

```bash
mkdir -p /workspace/pumpfun-comparison
tar -xzf paper-comparison-runtime.tar.gz -C /workspace/pumpfun-comparison
python3 -m venv /workspace/pumpfun-comparison/venv
/workspace/pumpfun-comparison/venv/bin/python -m pip install --upgrade pip
/workspace/pumpfun-comparison/venv/bin/python -m pip install \
  -r /workspace/pumpfun-comparison/paper-comparison-runtime/requirements-paper.txt
cd /workspace/pumpfun-comparison/paper-comparison-runtime
/workspace/pumpfun-comparison/venv/bin/python -m pytest tests/test_paper_only_safety.py
/workspace/pumpfun-comparison/venv/bin/python -m paper_only --self-check
```

Only after both commands succeed, start the public-feed paper run.
State and logs stay under `/workspace/pumpfun-comparison/state`, which
is not the extracted source tree and not `pumpfun-sniper`:

```bash
/workspace/pumpfun-comparison/venv/bin/python -m paper_only \
  --state /workspace/pumpfun-comparison/state
```

Stop with Ctrl-C. The process does not install a service.

Check `CHECKSUMS.sha256` inside the archive against the files you
extracted before installing. The review also publishes
`artifacts/paper-comparison-runtime.sha256` for the archive itself.

## Launch from a git checkout

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
