"""Shared logging setup for safe_harness.py, ralph_loop.py, and
real_repo_loop.py.

Status/diagnostic messages (tool execution, approval decisions, verification
results, non-convergence, errors) go through `logging` instead of bare
print() so they carry a level and timestamp and can be redirected or
filtered without touching the scripts. The model's own conversational
output and interactive prompts still use print() — that's the program's
actual output, not a log of its internal state.
"""

import logging
import os

LOG_LEVEL_ENV_VAR = "LOG_LEVEL"


def configure_logging():
    """Configure the root logger once, controlled by LOG_LEVEL (default
    INFO). Logs go to stderr so stdout stays free for the model's output
    and interactive prompts. logging.basicConfig() is a no-op if a handler
    is already configured, so calling this more than once is harmless.
    """
    level_name = os.environ.get(LOG_LEVEL_ENV_VAR, "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
