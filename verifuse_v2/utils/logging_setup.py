"""JSON structured logging setup for VeriFuse API."""
import json
import logging
import os
import time
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get("-"),
        }
        if record.exc_info:
            entry["traceback"] = self.formatException(record.exc_info)
        # Merge any extra= kwargs passed to log call
        _SKIP = {
            "args", "exc_info", "exc_text", "stack_info", "message",
            "msg", "levelname", "levelno", "pathname", "filename",
            "module", "funcName", "lineno", "created", "msecs",
            "relativeCreated", "thread", "threadName", "processName",
            "process", "name", "taskName",
        }
        for k, v in record.__dict__.items():
            if k not in _SKIP:
                entry[k] = v
        return json.dumps(entry, default=str)


def setup_logging(level: str = "INFO") -> None:
    fmt = JsonFormatter()
    # Stream handler (systemd journal)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    # File handler (structured JSONL)
    os.makedirs("verifuse_v2/logs", exist_ok=True)
    fh = logging.FileHandler("verifuse_v2/logs/api_structured.jsonl")
    fh.setFormatter(fmt)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(sh)
    root.addHandler(fh)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # Quiet noisy third-party loggers
    for noisy in ("uvicorn.access", "slowapi", "stripe", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
