"""structlog JSON logging, established day one per ELUMS_BUILD_SCHEDULE.md:
"log token counts and GPU timings from day one... Sunday's ledger is then
a query, not an archaeology project."

Convention, carried through every later milestone:
  - every line: request_id
  - job lines additionally: job_id
  - ML lines additionally: model, duration_ms, vram_peak_mb
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(*, level: int = logging.INFO) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.types.FilteringBoundLogger:
    return structlog.get_logger(name)
