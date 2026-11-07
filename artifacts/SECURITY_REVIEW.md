# Security and paper-comparison review

Packaging update: holder-concentration and freeze-authority reads fail
closed while `PAPER_COMPARE_LOCK=1`. A missing read is logged under
`blocked_missing_risk` and is not a clean trade. Entry cash is 0.1015 SOL
(0.1 principal + 0.001 fee + 0.0005 priority), not a 0.1 SOL total input.
The inert tree is `artifacts/paper-comparison-runtime.tar.gz`.

Data-flow update: age is wall time since create, so the existing
DexScreener path can run after 30 seconds. Candidates below 60, or
blocked because holder/freeze data was unread, are rescored up to 8
times in 10 minutes. The threshold stays 60. Curve and market cap stay
the launch snapshot. Missing inputs are logged in
`logs/score_diagnostics.jsonl` and are not filled in. A wall-clock jump
that monotonic time misses is recorded as `clock=wall`. That does not
unsuspend the host.



Review date: 2026-11-06 (America/New_York).
Fork reviewed: https://github.com/Jkurre697/solana-pumpfun-bot
Upstream: https://github.com/DeeKalshiWay/solana-pumpfun-bot
Commit reviewed: `9290bc9fb72a49f2955bada2ad3ff4b0d0f1df48`
("Add disclaimer: educational template, no profit claims", 2026-11-04 18:36 UTC).

This was a static review of source, license, dependency manifests, and
install entrypoints. Unreviewed installers were not executed.
`python main.py` was not started. No wallet was loaded. No transaction
was signed or sent. No Telegram, email, or other outbound message was
sent. The baseline directory `/workspace/pumpfun-sniper` is not on this
machine and was not modified. The comparison is not running.

## Verdict

No obfuscated payload, hardcoded attacker webhook, or hidden key
exfiltration was found in the Python, shell, PowerShell, Docker, or
workflow files that were searched.

The repository is still a real trading bot. Live signing is one
environment flag away from the default paper path. That is an explicit
blocker for running `main.py`, Docker, or `deploy/install.sh` as the
comparison. The paper harness added beside it refuses those paths.
It is safe to self-check offline. Starting `python -m paper_only` is a
separate decision for the parent machine: it opens public read-only
market feeds and writes only under `paper_compare_state/`.

Nothing in the README paper curve, the graduation-sniper notes, or this
harness is a verified profit result. Upstream's README already says
paper pnl was concentrated in a few tickers (about 68% in three names
in the quoted sqlite excerpt) and that thresholds were tuned on that
history.

## License

`LICENSE` is MIT, Copyright (c) 2026, plus a non-advice risk paragraph.
GitHub reports the license as "Other" because of that extra paragraph.
The copyright notice and permission text were left unchanged.
Attribution in this review: DeeKalshiWay is the upstream author of the
strategy code; this fork is Jkurre697/solana-pumpfun-bot.

## What was not executed

- `deploy/install.sh` (root, creates user `pump`, rsyncs to `/opt/pump_bot`, `pip install`, installs and **starts** systemd)
- `deploy/pump_bot.service` (`EnvironmentFile` `.env`, `ExecStart` `main.py`, `Restart=always`)
- `Dockerfile` / `docker-compose.yml` (`CMD python -u main.py`, `env_file: .env`)
- `make-dashboard.sh` (documents `curl -sSL .../make-dashboard.sh | bash`, clones upstream, pip-installs, starts `main.py`; default dashboard password in the script is `test123`)
- `install_*.ps1`, `run_*.ps1`, `start_bot.bat`, `open_firewall.ps1` (Task Scheduler persistence and a firewall opening for the dashboard)
- `python main.py`
- `tools/graduation_sniper.py`, `tools/preflight.py`, `tools/control_bot.py`
- Dependency installers other than a direct `pip install` of the declared
  runtime and test packages, with `playwright` left out of the runtime set
  used to execute tests. `playwright` is declared and unused.

## Dependency and cost notes

`requirements.txt`: aiohttp, playwright, tweepy, telethon, requests,
websockets, rich, python-dotenv, base58, loguru, solders. No `setup.py`,
no npm `postinstall`, no hashed pins. `requirements-dev.txt` includes
that file plus pytest, pytest-asyncio, mypy, ruff.

`playwright` is not imported. `deploy/install.sh` and the Dockerfile
delete that line before install. `tweepy` and `telethon` are optional
imports inside `detector/social_monitor.py`. The harness does not start
that monitor.

No paid API is required for the harness.

| Service | Role in the original bot | Harness |
|---|---|---|
| Helius RPC | Recommended in `.env.example`. Paid tiers exist. | Cleared. Public RPC only. |
| Birdeye | Optional key. Skipped in code when unset. | Cleared. Not called. |
| Twitter/X API | Influencer and social monitors. Paid tiers exist. | Cleared. Not started. |
| Telegram user API (Telethon) | Channel monitor. | Cleared. Not started. |
| Telegram bot API | Trade alerts, graduation alerts, control bot. | Cleared. `send_alert` returns under the lock. |
| SMTP | Daily email report. | Cleared. `send_report` returns under the lock. |
| Jupiter quote/swap | Price fallback and live swaps. | Not called. |
| Jito block engine | Live `sendTransaction` lane. Free tier, still a submit path. | URL blocked. Region cleared. |
| PumpPortal data WebSocket | Launch stream. Public, no key. Can 403. | Used for launches only. |
| PumpPortal `/api/trade-local` | Builds a transaction for the signer. | URL blocked. Not called. |
| pump.fun frontend API | Metadata polling. Public. | Used by the existing tracker when the harness is launched. |
| DexScreener | Public market data. Rate limited. | Fallback price, and scorer enrichment for older tokens. |
| Public Solana RPC and PublicNode | Account reads. Rate limited. | `getAccountInfo` only in the harness price reader. |

Dollar cost of the harness feeds is zero while those public endpoints
keep answering. The cost of a bad public-RPC hour is missing data, not
an invoice. Missing data is recorded as gaps, not as strategy pnl.

Pump.fun's own swap fee is not paid, because nothing is submitted. The
1% per side in the paper model is an accounting stand-in for that fee,
not a chain debit.

## Live-trading and secret paths

These exist and are intentional product features, not hidden malware.
They are the reason `main.py` is not the comparison process.

- `config.py` defaults `PAPER_TRADING` to true, then `load_dotenv(override=True)`. A `.env` with `PAPER_TRADING=false` turns on live trading and overrides the code default.
- `SOLANA_PRIVATE_KEY` is read into `config.PRIVATE_KEY`. `trader/wallet.py` base58-decodes it into a `solders` keypair.
- `trader/executor.py` and `trader/pumpportal_executor.py` sign a versioned transaction and POST JSON-RPC `sendTransaction`. PumpPortal's trade-local endpoint returns the unsigned bytes. Jito regional URLs are additional submit lanes.
- `trader/local_tx_builder.py` builds pump.fun buy/sell transactions. `USE_LOCAL_TX_BUILD` defaults false. Fee recipient constant `CebN5WGQ4jvEPvsVU4EoHEpgzq1VV7AbicfhtW4xC9iM` is the address the file documents as the pump.fun fee recipient. It is not used by the paper harness. This review did not re-fetch the on-chain global account.
- `main.py` constructs `SolanaWallet` and `TradeExecutor` when `PAPER_TRADING` is false. The paper branch uses `PaperWallet` (pubkey string `PAPER_WALLET_SIMULATED`) and `PaperExecutor` (signatures prefixed `PAPER_`).
- `logger/web_server.py` binds `0.0.0.0:8765`. Basic auth is off unless both dashboard env vars are set. POST handlers can emergency-stop and force-sell. The harness does not start it.
- `logger/telegram_alerts.py` POSTs to `api.telegram.org` when both bot token and chat id are set. `logger/daily_report.py` sends SMTP mail when configured.
- `tools/control_bot.py` can edit `.env` and start processes, and it constructs `TradeExecutor`.
- `tools/preflight.py` derives a keypair from `SOLANA_PRIVATE_KEY` and queries balance.
- `tools/graduation_sniper.py` is a separate paper book (size 0.25 SOL, its own friction, state under `logs/`). A search of that file found no keypair load and no `sendTransaction`. It does call Telegram alerts when tokens are set. It was not started. It is not the strategy this harness runs.
- PumpPortal and pump.fun clients set a browser `User-Agent` and `Origin`. That is client disguise against a public API, not a callback to another host.
- `main.py` PID check on Windows shells out to PowerShell `Get-CimInstance`. The harness does not use that lock.

Search terms that did not show a secret sink: `webhook.site`, Discord webhook URLs, paste sites, `requestAirdrop`, a second hardcoded destination wallet. `base64.b64decode` uses are transaction or RPC account bytes and HTTP Basic auth for the dashboard, not a bundled payload.

## Paper-mode escape paths in the original process

Running `main.py` with the default flag is paper, until any of these:

1. `.env` or the shell sets `PAPER_TRADING=false` and a real key. Dotenv uses `override=True`, so the file wins over the environment.
2. systemd and Docker load `.env` and start `main.py` with no forced paper flag.
3. The dashboard force-sell calls `RiskManager._force_sell`, which calls `executor.sell`. In live mode that is a real sell.
4. `SYNTHETIC_INJECT` is refused when not in paper. That guard does not cover the live flag itself.
5. Auto-tune rewrites the score floor from recent trades and persists `logs/auto_tune_state.json`. A comparison that wants frozen thresholds cannot leave that loop on.
6. Adaptive sizing changes the next order with win rate. That is compounding-style sizing, which this comparison is not supposed to use.
7. Paper state files are relative `logs/`. A second process in the same directory reloads the other bot's wallet, positions, and tuner state.

The harness answers those by refusing to be `main.py`, skipping dotenv, blanking secrets, raising in the signer constructors, blocking submit URLs and RPC methods, forcing auto-tune and adaptive size off, and `chdir` into a dedicated state directory.

## Strategy identity

Two paper strategies live in this commit.

1. **Main pipeline.** `PumpFunMonitor` plus `SignalScorer` plus `RiskManager`. This is the book the README ties to the concentrated paper pnl. The harness runs these modules.
2. **Graduation sniper.** `tools/graduation_sniper.py`, described in its own docstring as the later scalp pivot, 0.25 SOL, different exits. The harness does not run it. Calling a graduation-sniper result a test of the README strategy would be false.

The harness is **upstream decision modules, isolated**. It is not a line-by-line reimplementation of the scorer, and it is not an unmodified `main.py` run. Fidelity gaps, all stated in `paper_only/README.md` and written again into `logs/PAPER_COMPARE_PIN.json` on launch:

- README ladder/stop/time-exit table disagrees with `config.py`. Frozen values are the code defaults at the pin (score floor 60, curve band 30–80%, take-profit +50/100/200 selling 25%, stop 15%, panic 25%, time exit 5 minutes, early rug −5% inside 60 seconds, no-movement 90 seconds inside ±3%, max 3 positions, 0.50 SOL exposure, symbol cap 10% of the 1.0 SOL book).
- Curve principal is 0.1 SOL. Entry cash is 0.1015 SOL (principal plus 1% fee plus 0.0005 priority). That is not the baseline's 0.1 SOL total input. Fills are not claimed to match.
- With the lock on, holder and freeze-authority reads must succeed or the name is blocked and is not a clean trade. Upstream without the lock still fail-opens those reads.
- Cost model is 1% per side, 2% adverse slippage per side, 0.0005 SOL priority per transaction. Upstream realistic paper friction is not used. Upstream configured live priority caps (0.001 buy / 0.005 sell) are not used.
- Jupiter is not queried. Post-migration marks fall through to DexScreener.
- Twitter, Telegram, email, dashboard, trending scanner, and social monitor are not started. Influencer bonuses stay at zero.
- Launch detection is PumpPortal `subscribeNewToken`, not the baseline's `logsSubscribe` primary/PublicNode pair. PublicNode is only the backup for bonding-curve account reads.
- Host-freeze handling (pause entries 90 seconds, flatten at a stall of at least 300 seconds, separate clean / freeze-hit / data-gap stats) is harness policy around the strategy. Detection starts at a 5 second late heartbeat. Upstream `RiskManager` does not implement that policy.

## Tests

`tests/test_paper_only_safety.py` (offline):

- Every `config.py` `_env_*` knob is set by the lock.
- Buy/sell math matches the 0.1 / 1% / 2% / 0.0005 model, including wallet cash.
- A non-0.1 size is rejected by the executor and by the sizing gate.
- Freeze, flatten, entry pause, and bucket files stay separate from clean legs.
- `sendTransaction`, `sendRawTransaction`, PumpPortal trade-local, and Jito submit URLs raise. `getAccountInfo` does not.
- State paths named `pumpfun-sniper`, and the repo root, are refused.
- Runtime harness modules do not import the signer modules.
- `--self-check` in a fresh process ignores a hostile `.env` and a hostile shell (`PAPER_TRADING=false`, a dummy key, Helius URL, score floor 1) and still reports paper, 0.1 SOL, score floor 60, empty key.
- `main.py` under the lock exits 3.
- An import blocker refuses `trader.executor`.

`tests/test_paper_executor.py` gained a loop fallback so those sync tests still run after pytest-asyncio 1.x closes the main-thread loop. That is test-only.

Full `pytest tests` passed in this review environment after that fallback (Python 3.12). `mypy tests/` passed. `ruff check` passed on the touched files.

## Files

| Path | Role |
|---|---|
| `paper_only/README.md` | Launch instructions for the parent machine |
| `paper_only/` | Lock, costs, executor, feed health, runner, offline self-check |
| `tests/test_paper_only_safety.py` | No-sign / no-send and fixed-cost tests |
| `config.py`, `main.py`, `trader/wallet.py`, `trader/executor.py`, `trader/pumpportal_executor.py`, `trader/local_tx_builder.py`, `logger/telegram_alerts.py`, `logger/daily_report.py` | Lock refusals. Default behavior is unchanged when the lock is unset. |
| `artifacts/SECURITY_REVIEW.md` | This note |
| `artifacts/PINNED_COMMIT.txt` | Commit pin |
| `artifacts/paper-only-harness.patch` | Diff against `9290bc9` for the parent to apply on a clean tree. Do not apply it on top of the PR branch. |

## Parent launch, after you accept the review

The comparison is not running here. Nothing has been installed as a service.
Do not clone the repo for this run. Use the archive.

```bash
mkdir -p /workspace/pumpfun-comparison
tar -xzf artifacts/paper-comparison-runtime.tar.gz -C /workspace/pumpfun-comparison
python3 -m venv /workspace/pumpfun-comparison/venv
/workspace/pumpfun-comparison/venv/bin/python -m pip install --upgrade pip
/workspace/pumpfun-comparison/venv/bin/python -m pip install \
  -r /workspace/pumpfun-comparison/paper-comparison-runtime/requirements-paper.txt
cd /workspace/pumpfun-comparison/paper-comparison-runtime
/workspace/pumpfun-comparison/venv/bin/python -m pytest tests/test_paper_only_safety.py
/workspace/pumpfun-comparison/venv/bin/python -m paper_only --self-check
/workspace/pumpfun-comparison/venv/bin/python -m paper_only \
  --state /workspace/pumpfun-comparison/state
```

Verify `CHECKSUMS.sha256` inside the archive before installing. Stop the
feed process with Ctrl-C. It does not install a service. Do not point
`--state` at `pumpfun-sniper`, and do not reset the baseline.
