from typing import Any

from app.odr_executor.core.logger import base_log, TaskLoggerAdapter
from app.odr_executor.core.guard import ProcessGuard


class FFmpegGuard(ProcessGuard):
    def __init__(self) -> None:
        super().__init__("FFmpeg")
        self._log = TaskLoggerAdapter(base_log, {"tag": self.tag})
        self._base_cmd = ["ffmpeg"]

    def _parse_command(self, cmd: dict[str, Any]) -> list[str]:
        self._log.info("parsing command for ffmpeg process...")

        # TODO(yangxinxin): Implement actual command parsing logic based on the expected structure of `cmd`.
        cmd_list = self._base_cmd

        return cmd_list
