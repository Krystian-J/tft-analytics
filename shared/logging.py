import logging
import sys

import structlog


def setup_logging() -> None:
    """
    Configures structlog for the entire application.
    Call once at startup in both crawler/main.py and backend/main.py.

    Outputs structured JSON logs — each log line is a JSON object
    making it easy to trace a match_id or puuid through the pipeline.

    Example output:
    {
        "event": "match fetched",
        "match_id": "EUW1_7737852228",
        "level": "info",
        "timestamp": "2026-02-19T12:00:00.000Z"
    }
    """

    # Set standard library logging level
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )

    # Silence noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("clickhouse_connect").setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            # Add log level to every event
            structlog.stdlib.add_log_level,
            # Add timestamp to every event
            structlog.processors.TimeStamper(fmt="iso"),
            # Render as JSON
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Returns a logger bound with the given name.
    Use this instead of importing structlog directly.

    Usage:
        from shared.logging import get_logger
        logger = get_logger(__name__)
        logger.info("match fetched", match_id="EUW1_123", puuid="abc...")
        logger.error("api error", status_code=429, endpoint="/matches")
    """
    return structlog.get_logger(name)
