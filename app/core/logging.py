import structlog
import logging
import sys


def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        format="%(message)s", stream=sys.stdout, level=getattr(logging, level)
    )

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
