"""The app's single logger. Every service imports this one instance:
    from shared.logger import logger
Level comes from LOG_LEVEL (default INFO); output goes to stderr."""

import logging
import os

logger = logging.getLogger("spacey")
if not logger.handlers:
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
