"""python -m paper_only [--self-check] [--state DIR]

Does not connect a wallet. --self-check stays offline.
The default run opens public read-only market feeds. It is not started
by importing this module.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from paper_only.lock import install_lock


def main(argv: list[str] | None = None) -> int:
    install_lock()
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Isolated paper comparison. No wallet. No transaction sends.",
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Offline lock check. Does not open a feed.",
    )
    parser.add_argument(
        "--state",
        default="",
        help="Dedicated state directory. Default: <repo>/paper_compare_state",
    )
    args = parser.parse_args(argv)
    if args.self_check:
        from paper_only.selfcheck import run_self_check
        return run_self_check()
    from paper_only.runner import launch
    state = Path(args.state) if args.state else repo / "paper_compare_state"
    asyncio.run(launch(state))
    return 0


if __name__ == "__main__":
    sys.exit(main())
