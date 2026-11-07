"""File and stdout logging without the Rich dashboard."""

from __future__ import annotations

import os
import sys

from loguru import logger


def setup_logging() -> None:
    os.makedirs("logs", exist_ok=True)
    logger.remove()
    logger.add(
        "logs/pump_bot.log",
        level="INFO",
        rotation="20 MB",
        retention=5,
        compression="gz",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
        enqueue=True,
    )
    logger.add(
        "logs/trades.log",
        level="SUCCESS",
        filter=lambda record: any(
            word in record["message"] for word in ("BUY", "SELL", "POSITION")
        ),
        format="{time:YYYY-MM-DD HH:mm:ss} | {message}",
    )
    logger.add(
        sys.stdout,
        level="INFO",
        format="{time:HH:mm:ss} | {level:<8} | {message}",
    )
