"""Single-line JSON log records, shaped for Cloud Logging.

Cloud Run collects stdout. When a line is valid JSON, Cloud Logging parses it
into structured fields and promotes `severity` to the entry's level, which is
what makes "show me every ERROR for this household" a query rather than a grep.
"""

import json
import logging

from core.request_id import get_log_context


class JsonFormatter(logging.Formatter):
    """Render a record as one JSON line.

    Never raises. A formatter that raises loses the log line *and* surfaces
    inside whatever was being logged — usually an error, which is exactly when
    the line matters most. Hence `default=str` and the guarded `getMessage`.
    """

    def format(self, record: logging.LogRecord) -> str:
        try:
            message = record.getMessage()
        except Exception:  # a bad %-format argument must not kill the request
            message = str(record.msg)

        payload = {
            "severity": record.levelname,
            "message": message,
            "logger": record.name,
            **get_log_context(),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)
