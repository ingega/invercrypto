# invercrypto/strategy/common_files/logger.py
"""
Centralized logging configuration for Invercrypto.

Features
--------
- Singleton logger
- Console logging (CloudWatch compatible)
- Rotating log files
- UTC timestamps
- Millisecond precision
- Optional file logging
- Optional JSON logging
- Environment-variable configuration
"""

import json
import logging
import os
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from common_files.paths import LOG_FILE, LOG_LIVE_FILE

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

ENABLE_FILE_LOG = (
    os.getenv("ENABLE_FILE_LOG", "true").lower()
    in ("1", "true", "yes")
)

JSON_LOGS = (
    os.getenv("JSON_LOGS", "false").lower()
    in ("1", "true", "yes")
)

MAX_LOG_SIZE = 5 * 1024 * 1024
BACKUP_COUNT = 10


# -----------------------------------------------------------------------------
# JSON Formatter
# -----------------------------------------------------------------------------

class JsonFormatter(logging.Formatter):
    """
    CloudWatch-friendly JSON formatter.
    """

    converter = time.gmtime

    def format(self, record):

        payload = {
            "timestamp": self.formatTime(
                record,
                "%Y-%m-%dT%H:%M:%S"
            ) + f".{int(record.msecs):03d}Z",

            "level": record.levelname,

            "logger": record.name,

            "process": record.process,

            "module": record.module,

            "function": record.funcName,

            "line": record.lineno,

            "message": record.getMessage(),
        }

        # Include custom fields supplied with "extra="
        reserved = {
            "name", "msg", "args", "levelname",
            "levelno", "pathname", "filename",
            "module", "exc_info", "exc_text",
            "stack_info", "lineno", "funcName",
            "created", "msecs", "relativeCreated",
            "thread", "threadName", "processName",
            "process", "message"
        }

        for key, value in record.__dict__.items():
            if key not in reserved:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


# -----------------------------------------------------------------------------
# Plain Formatter
# -----------------------------------------------------------------------------

class UTCFormatter(logging.Formatter):

    converter = time.gmtime


TEXT_FORMATTER = UTCFormatter(
    "%(asctime)s.%(msecs)03d | %(levelname)-8s | "
    "%(process)d | %(name)s | %(message)s",
    "%Y-%m-%d %H:%M:%S",
)

JSON_FORMATTER = JsonFormatter()


# -----------------------------------------------------------------------------
# Logger
# -----------------------------------------------------------------------------

def get_logger(name: str = "Invercrypto",
               log_live: bool = False) -> logging.Logger:

    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(LOG_LEVEL)
    logger.propagate = False

    formatter = JSON_FORMATTER if JSON_LOGS else TEXT_FORMATTER

    # -------------------------------------------------------------------------
    # Console (CloudWatch)
    # -------------------------------------------------------------------------

    console = logging.StreamHandler()

    console.setLevel(LOG_LEVEL)

    console.setFormatter(formatter)

    logger.addHandler(console)

    # -------------------------------------------------------------------------
    # Rotating File
    # -------------------------------------------------------------------------
    if log_live:
        log_file = LOG_LIVE_FILE
    else:
        log_file = LOG_FILE

    if ENABLE_FILE_LOG:

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=MAX_LOG_SIZE,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )

        file_handler.setLevel(LOG_LEVEL)

        file_handler.setFormatter(formatter)

        logger.addHandler(file_handler)

    return logger