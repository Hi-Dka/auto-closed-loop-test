from app.odr_executor.core.logger import base_log, TaskLoggerAdapter
from app.odr_executor.core.guard import ProcessGuard
from typing import Any


class DabModGuard(ProcessGuard):
    def __init__(self) -> None:
        super().__init__("DabMod")
        self._base_cmd = ["odr-dabmod"]
        self._log = TaskLoggerAdapter(base_log, {"tag": self.tag})

    def _parse_command(self, cmd: dict[str, Any]) -> list[str]:

        self._log.info("parsing command for DAB modulator...")

        if "mode" not in cmd:
            self._log.warning(
                "Mode not specified in new command, using default value: 1"
            )
            cmd["mode"] = 1

        if "format" not in cmd:
            self._log.warning(
                "Format not specified in new command, using default value: s8"
            )
            cmd["format"] = "s8"

        if "gain" not in cmd:
            self._log.warning(
                "Gain not specified in new command, using default value: 0.8"
            )
            cmd["gain"] = 0.8
        if "gainmode" not in cmd:
            self._log.warning(
                "Gain mode not specified in new command, using default value: max"
            )
            cmd["gainmode"] = "max"

        if "rate" not in cmd:
            self._log.warning(
                "Sample rate not specified in new command, using default value: 2048000"
            )
            cmd["rate"] = 2048000

        cmd_list = self._base_cmd + [
            "/tmp/fifos/mux2mod.fifo",
            "-f",
            "/tmp/fifos/mod2hackrf.fifo",
            "-m",
            str(cmd["mode"]),
            "-r",
            str(cmd["rate"]),
            "-F",
            str(cmd["format"]),
            "-a",
            str(cmd["gain"]),
            "-g",
            str(cmd["gainmode"]),
        ]
        return cmd_list
