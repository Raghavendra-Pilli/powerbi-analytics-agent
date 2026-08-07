"""Structured logging for the Power BI Analytics Agent."""

import logging
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


class StructuredFormatter(logging.Formatter):
    """JSON-structured log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "module": record.module,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "component"):
            log_entry["component"] = record.component
        if hasattr(record, "action"):
            log_entry["action"] = record.action
        return json.dumps(log_entry)


class ConsoleFormatter(logging.Formatter):
    """Human-readable console formatter with colors."""

    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[1;31m",  # Bold Red
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        prefix = f"{color}[{record.levelname}]{self.RESET}"
        component = getattr(record, "component", record.module)
        return f"{prefix} {component}: {record.getMessage()}"


def setup_logger(
    level: str = "INFO",
    log_file: str | None = None,
    structured: bool = True,
    console: bool = True,
) -> logging.Logger:
    """Configure the root agent logger."""
    logger = logging.getLogger("pbi_agent")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(ConsoleFormatter())
        logger.addHandler(console_handler)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        if structured:
            file_handler.setFormatter(StructuredFormatter())
        else:
            file_handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(module)s: %(message)s"
            ))
        logger.addHandler(file_handler)

    return logger


def get_logger(component: str) -> logging.LoggerAdapter:
    """Get a logger adapter tagged with a component name."""
    logger = logging.getLogger("pbi_agent")
    return logging.LoggerAdapter(logger, {"component": component})
