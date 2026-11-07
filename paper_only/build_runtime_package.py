"""Build artifacts/paper-comparison-runtime.tar.gz.

Copies the paper harness and the modules it imports. Omits git metadata,
.env, signer modules, main.py, and installers. Does not start a feed.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE_PARENT = Path("/tmp/paper-comparison-runtime-stage")
PKG_NAME = "paper-comparison-runtime"
DEST = STAGE_PARENT / PKG_NAME
TAR_PATH = ROOT / "artifacts" / "paper-comparison-runtime.tar.gz"
OUTER_SUM = ROOT / "artifacts" / "paper-comparison-runtime.sha256"

RUNTIME_FILES = [
    "LICENSE",
    "config.py",
    "analyzer/__init__.py",
    "analyzer/auto_tuner.py",
    "analyzer/counterfactual.py",
    "analyzer/regime_filter.py",
    "analyzer/rug_memory.py",
    "analyzer/signal_fusion.py",
    "analyzer/signal_scorer.py",
    "detector/__init__.py",
    "detector/creator_tracker.py",
    "detector/dex_monitor.py",
    "detector/holder_filter.py",
    "detector/influencer_monitor.py",
    "detector/pumpfun_monitor.py",
    "detector/pumpfun_tracker.py",
    "detector/social_monitor.py",
    "detector/wallet_intel.py",
    "detector/whale_tracker.py",
    "detector/x_feed.py",
    "logger/__init__.py",
    "logger/telegram_alerts.py",
    "logger/trade_db.py",
    "risk/__init__.py",
    "risk/manager.py",
    "trader/__init__.py",
    "trader/paper_wallet.py",
    "paper_only/__init__.py",
    "paper_only/__main__.py",
    "paper_only/README.md",
    "paper_only/book.py",
    "paper_only/costs.py",
    "paper_only/executor.py",
    "paper_only/feedhealth.py",
    "paper_only/frozen.py",
    "paper_only/lock.py",
    "paper_only/logging_setup.py",
    "paper_only/net_guard.py",
    "paper_only/prices.py",
    "paper_only/risk_gate.py",
    "paper_only/runner.py",
    "paper_only/selfcheck.py",
    "paper_only/sizing.py",
    "tests/__init__.py",
    "tests/test_paper_only_safety.py",
    "artifacts/SECURITY_REVIEW.md",
    "artifacts/PINNED_COMMIT.txt",
]

FORBIDDEN_PARTS = {".git", ".env", "pumpfun-sniper"}
UNPINNED = [
    "aiohttp>=3.9,<4",
    "websockets>=9,<12",
    "loguru>=0.7,<0.8",
    "python-dotenv>=1.0,<2",
    "solders>=0.21,<0.30",
    "pytest>=8",
    "pytest-asyncio>=0.23",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _copy_tree() -> None:
    if STAGE_PARENT.exists():
        shutil.rmtree(STAGE_PARENT)
    DEST.mkdir(parents=True)
    for rel in RUNTIME_FILES:
        src = ROOT / rel
        if not src.is_file():
            raise SystemExit(f"missing runtime file: {rel}")
        if any(part in FORBIDDEN_PARTS or part.startswith(".env") for part in Path(rel).parts):
            raise SystemExit(f"refusing to package {rel}")
        target = DEST / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    shutil.copy2(ROOT / "paper_only" / "README.md", DEST / "README.md")
    commit = (ROOT / "paper_only" / "frozen.py").read_text(encoding="utf-8")
    pin = "9290bc9fb72a49f2955bada2ad3ff4b0d0f1df48"
    if pin not in commit:
        raise SystemExit("frozen.py lost the source pin")
    head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    (DEST / "SOURCE_COMMIT.txt").write_text(
        "\n".join([
            f"strategy_commit={pin}",
            "strategy_repo=https://github.com/Jkurre697/solana-pumpfun-bot",
            "upstream_repo=https://github.com/DeeKalshiWay/solana-pumpfun-bot",
            "license=MIT; see LICENSE. Copyright (c) 2026.",
            f"git_head_at_package_time={head.stdout.strip() or 'uncommitted'}",
            "cash_entry_sol=0.1015",
            "cash_note=0.1 curve principal + 0.001 fee + 0.0005 priority; not a 0.1 total input",
            "comparison_not_running=true",
            "",
        ]),
        encoding="utf-8",
    )


def _write_requirements(venv: Path) -> None:
    py = venv / "bin" / "python"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    subprocess.run([str(py), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    subprocess.run([str(py), "-m", "pip", "install", *UNPINNED], check=True)
    freeze = subprocess.run(
        [str(py), "-m", "pip", "freeze"],
        capture_output=True, text=True, check=True,
    )
    lines = [
        "# Pinned install for the paper-comparison runtime.",
        "# No playwright, tweepy, telethon, or rich.",
        "# No paid API clients are required.",
        "",
    ]
    for line in freeze.stdout.splitlines():
        if not line or line.startswith("-e ") or "pip==" in line.lower():
            continue
        lines.append(line)
    lines.append("")
    text = "\n".join(lines)
    (DEST / "requirements-paper.txt").write_text(text, encoding="utf-8")
    (ROOT / "requirements-paper.txt").write_text(text, encoding="utf-8")


def _test_package(venv: Path) -> None:
    py = venv / "bin" / "python"
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PAPER_COMPARE_LOCK", None)
    proc = subprocess.run(
        [str(py), "-m", "pytest", "tests/test_paper_only_safety.py", "-q", "--tb=short", "-p", "no:cacheprovider"],
        cwd=DEST,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit("packaged tests failed")
    proc = subprocess.run(
        [str(py), "-m", "paper_only", "--self-check"],
        cwd=DEST,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit("packaged self-check failed")
    # Confirm the parent state path is accepted and the baseline path is not.
    code = (
        "from pathlib import Path\n"
        "from paper_only.runner import assert_safe_state_dir\n"
        "repo = Path('.').resolve()\n"
        "ok = Path('/workspace/pumpfun-comparison/state')\n"
        "assert assert_safe_state_dir(ok, repo) == ok.resolve()\n"
        "try:\n"
        "    assert_safe_state_dir(Path('/workspace/pumpfun-sniper'), repo)\n"
        "except RuntimeError:\n"
        "    pass\n"
        "else:\n"
        "    raise SystemExit('baseline path was accepted')\n"
    )
    proc = subprocess.run([str(py), "-c", code], cwd=DEST, env=env, check=False)
    if proc.returncode != 0:
        raise SystemExit("state-dir check failed")


def _checksum_and_tar() -> None:
    for cache in DEST.rglob("__pycache__"):
        shutil.rmtree(cache)
    rows = []
    for path in sorted(DEST.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "CHECKSUMS.sha256":
            continue
        rel = path.relative_to(DEST).as_posix()
        if ".git" in rel.split("/") or rel.startswith(".env"):
            raise SystemExit(f"forbidden packaged path {rel}")
        rows.append(f"{_sha256(path)}  {rel}")
    (DEST / "CHECKSUMS.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")
    TAR_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TAR_PATH.exists():
        TAR_PATH.unlink()
    with tarfile.open(TAR_PATH, "w:gz") as archive:
        archive.add(DEST, arcname=PKG_NAME)
    OUTER_SUM.write_text(
        f"{_sha256(TAR_PATH)}  artifacts/paper-comparison-runtime.tar.gz\n",
        encoding="utf-8",
    )


def main() -> None:
    venv = Path("/tmp/paper-comparison-runtime-venv")
    if venv.exists():
        shutil.rmtree(venv)
    _copy_tree()
    _write_requirements(venv)
    _test_package(venv)
    _checksum_and_tar()
    print(f"wrote {TAR_PATH}")
    print(OUTER_SUM.read_text(encoding="utf-8").strip())


if __name__ == "__main__":
    main()
