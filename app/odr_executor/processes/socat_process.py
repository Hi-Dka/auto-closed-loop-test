from app.odr_executor.core.logger import base_log, TaskLoggerAdapter
from app.odr_executor.core.guard import ProcessGuard
from typing import Any


class SocatGuard(ProcessGuard):
    def __init__(self, task_id: str, port: int, fifo: str) -> None:
        super().__init__(f"Socat-{task_id}")
        self._base_cmd = ["socat"]
        self._port = port
        self._fifo = fifo
        self._log = TaskLoggerAdapter(base_log, {"tag": self.tag})

    def _parse_command(self, cmd: dict[str, Any]) -> list[str]:

        self._log.info("parsing command for audio encoder...")

        cmd_list = self._base_cmd + [
            "-u",
            f"UDP-RECV:{self._port},reuseaddr",
            f"FILE:{self._fifo}",
        ]

        return cmd_list
