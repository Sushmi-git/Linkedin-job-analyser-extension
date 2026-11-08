import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILE = Path(__file__).resolve().parents[1] / "logs" / "backend.log"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
MAX_LOG_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3


def configure_logging() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    root_logger = logging.getLogger()
    handler = next(
        (
            existing
            for existing in root_logger.handlers
            if isinstance(existing, RotatingFileHandler)
            and Path(existing.baseFilename) == LOG_FILE
        ),
        None,
    )
    if handler is None:
        handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=MAX_LOG_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(LOG_FORMAT))

    root_logger.setLevel(logging.INFO)
    if handler not in root_logger.handlers:
        root_logger.addHandler(handler)

    for name in ("uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        if not logger.propagate and handler not in logger.handlers:
            logger.addHandler(handler)
