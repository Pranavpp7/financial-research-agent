"""
Centralized structlog configuration for financial-research-agent.

Call `configure_logging()` once at application startup (main.py and
celery_app.py). All modules then do:
    import structlog
    logger = structlog.get_logger(__name__)

Behaviour:
  - JSONRenderer when ENV=production, colored ConsoleRenderer otherwise.
  - Routed through stdlib logging (ProcessorFormatter) so uvicorn/Celery
    logs share the same formatting and `LOG_LEVEL` applies to everything.
  - Every event carries service="financial-research-agent".
  - Log level from the LOG_LEVEL env var (default INFO).

Idempotent: safe to call more than once (e.g. per Celery worker process).
"""
import logging
import os

import structlog


def _add_service(logger, method_name, event_dict):
    """Inject a stable service field on every log event."""
    event_dict.setdefault("service", "financial-research-agent")
    return event_dict


def configure_logging() -> None:
    env = os.getenv("ENV", "development").lower()
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    timestamper = structlog.processors.TimeStamper(fmt="iso")

    # Processors shared by structlog-native and foreign (stdlib) records.
    pre_chain = [
        structlog.contextvars.merge_contextvars,
        _add_service,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.stdlib.PositionalArgumentsFormatter(),
    ]

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if env == "production"
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=pre_chain
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=pre_chain,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
