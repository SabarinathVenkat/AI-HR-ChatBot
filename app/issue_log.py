"""The issue log: a file to open when something went wrong.

Every event is one line: time, level, what happened, then key=value details (who, which request, which file, which
error code, how long). Errors add their type, message and full traceback underneath. Values with spaces are quoted so a
line can be searched or read back by a script. The file rotates (5 MB, 5 old files), so it never fills the disk.

The log holds ids, names, file names, sizes, codes and messages. It never holds the text of a resume, a password or a token.

Where it goes: RESUME_LOG_FILE, default var/logs/resume_builder.log.
"""
import json
import logging
import logging.handlers
from pathlib import Path

NAME = "resume.issues"
DEFAULT_PATH = "var/logs/resume_builder.log"
MAX_BYTES = 5_000_000
BACKUPS = 5
_LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}
_logger = logging.getLogger(NAME)
_logger.setLevel(logging.INFO)


def configure(path: str | Path = DEFAULT_PATH) -> Path:
    """Start writing the log to `path` (the folder is created). Calling it again for the same file changes nothing."""
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    for handler in _logger.handlers:
        if getattr(handler, "baseFilename", None) == str(path):
            return path
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"))
    _logger.addHandler(handler)
    return path


def _value(value) -> str:
    text = str(value)
    if text and not any(c.isspace() or c in '"=' for c in text):
        return text
    return json.dumps(text, ensure_ascii=False)


def event(what: str, /, *, level: str = "info", error: BaseException | None = None, **fields) -> None:
    """Record one event. Fields that are None are left out. Never raises: logging must not break the request."""
    try:
        parts = [what]
        if error is not None:
            fields = {**fields, "error_type": type(error).__name__, "error_message": str(error)}
        parts += [f"{key}={_value(value)}" for key, value in fields.items() if value is not None]
        _logger.log(_LEVELS[level], " ".join(parts), exc_info=error if error is not None and error.__traceback__ else None)
    except Exception:  # noqa: BLE001 - a logging problem must never become a user's problem
        pass
