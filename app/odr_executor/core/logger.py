import logging
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any, cast


class ColorFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[1;41m",
    }
    RESET = "\033[0m"

    def format(self, record):
        if not hasattr(record, "tag"):
            record.tag = "SYSTEM"
        color = self.COLORS.get(record.levelname, self.RESET)
        orig_levelname = record.levelname
        record.levelname = f"{color}{orig_levelname}{self.RESET}"
        result = super().format(record)
        record.levelname = orig_levelname
        return result


LOG_FORMAT = "%(levelname)s: [%(tag)s]: %(message)s"

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(ColorFormatter(LOG_FORMAT))

logging.basicConfig(level=logging.INFO, handlers=[handler])

base_log = logging.getLogger("odr_executor")


class TaskLoggerAdapter(logging.LoggerAdapter[logging.Logger]):
    def process(
        self, msg: str, kwargs: MutableMapping[str, Any]
    ) -> tuple[str, MutableMapping[str, Any]]:
        default_tag = "SYSTEM"
        if isinstance(self.extra, Mapping):
            tag = str(self.extra.get("tag", default_tag))
        else:
            tag = default_tag

        current_extra = kwargs.get("extra")
        merged_extra: dict[str, Any] = {}
        if isinstance(current_extra, Mapping):
            typed_extra = cast(Mapping[str, Any], current_extra)
            merged_extra.update(typed_extra)
        merged_extra.setdefault("tag", tag)
        kwargs["extra"] = merged_extra
        return msg, kwargs
