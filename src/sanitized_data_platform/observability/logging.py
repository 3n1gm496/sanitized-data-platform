from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sanitized_data_platform.config.settings import LoggingSettings


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for attribute in ("request_id", "method", "path", "status_code", "duration_ms"):
            value = getattr(record, attribute, None)
            if value is not None:
                payload[attribute] = value
        return json.dumps(payload, default=str)


def configure_logging(settings: LoggingSettings) -> None:
    handler = logging.StreamHandler()
    if settings.json_format:
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(settings.level)
    root.addHandler(handler)
