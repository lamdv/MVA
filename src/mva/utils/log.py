"""Logging configuration for MVA.

Call ``setup_logging(cfg)`` once at startup (from main() / web_main()).
Every module then acquires its own child logger via ``get_logger(__name__)``.

Config keys (all optional):
    log_level:  DEBUG | INFO | WARNING | ERROR  (default: INFO)
    log_stdout: true | false                    (default: true)
    log_file:   path/to/notebook.log            (default: no file)
"""
import logging
import sys
from pathlib import Path
from typing import Any

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(cfg: dict[str, Any]) -> None:
    """Configure the ``private_notebook`` logger tree from *cfg*."""
    level_name = str(cfg.get("log_level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    logger = logging.getLogger("private_notebook")
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    if cfg.get("log_stdout", True):
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(formatter)
        logger.addHandler(sh)

    log_file = cfg.get("log_file")
    if log_file:
        fh = logging.FileHandler(Path(log_file).expanduser(), encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the ``private_notebook`` namespace."""
    return logging.getLogger(f"private_notebook.{name}")
