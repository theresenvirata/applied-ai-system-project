"""
Logging setup shared by the app (src/main.py) and the evaluator (src/evaluate.py).

- Everything at INFO and above goes to logs/recommender.log (profiles, results, weights).
- Only WARNING and above is shown in the console, so normal output stays readable.
"""

import logging
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
DEFAULT_LOG_FILE = os.path.join(LOG_DIR, "recommender.log")

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

_configured = False


def setup_logging(log_file: str = DEFAULT_LOG_FILE, console_level: int = logging.WARNING) -> None:
    """Configures logging once. Calling it again does nothing, so handlers are never duplicated."""
    global _configured
    if _configured:
        return

    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root.addHandler(console_handler)

    _configured = True
