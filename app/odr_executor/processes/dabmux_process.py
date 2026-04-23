import os

from typing import Any

from app.odr_executor.core.logger import base_log, TaskLoggerAdapter
from app.odr_executor.core.guard import ProcessGuard


class DabMuxGuard(ProcessGuard):
    def __init__(self) -> None:
        super().__init__("DabMux")
        self._log = TaskLoggerAdapter(base_log, {"tag": self.tag})
        self._base_cmd = ["odr-dabmux"]

    def _parse_command(self, cmd: dict[str, Any]) -> list[str]:
        self._log.info("parsing command for DAB muxer...")

        advanced_config_path = os.getenv(
            "DABMUX_ADVANCED_CONFIG_PATH",
            "/home/hidka/Project/Auto-Closed-Loop-Test/config/odr_executor/dabmux/advanced.mux",
        )
        if cmd.get("filename"):
            advanced_config_path = f"/tmp/dabmux/{cmd['filename']}"
            os.makedirs("/tmp/dabmux", exist_ok=True)

            file_bytes = cmd.get("file_bytes")
            if isinstance(file_bytes, (bytes, bytearray)):
                with open(advanced_config_path, "wb") as f:
                    f.write(file_bytes)
            else:
                content = cmd.get("content")
                with open(advanced_config_path, "w", encoding="utf-8") as f:
                    f.write(str(content or ""))

        cmd_list = self._base_cmd + [advanced_config_path]

        return cmd_list
