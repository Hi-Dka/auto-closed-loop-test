from app.odr_executor.core.logger import base_log, TaskLoggerAdapter
from app.odr_executor.core.guard import ProcessGuard
from typing import Any


class HackRFGuard(ProcessGuard):
    def __init__(self) -> None:
        super().__init__("HackRF")
        self._base_cmd = ["hackrf_transfer"]
        self._log = TaskLoggerAdapter(base_log, {"tag": self.tag})

    def _parse_command(self, cmd: dict[str, Any]) -> list[str]:

        self._log.info("parsing command for HackRF...")

        if "freq_hz" not in cmd:
            self._log.warning(
                "Frequency not specified in new command, using default value: 227360000"
            )
            cmd["freq_hz"] = 227360000

        if "sample_rate_hz" not in cmd:
            self._log.warning(
                "Sample rate not specified in new command, using default value: 2048000"
            )
            cmd["sample_rate_hz"] = 2048000

        if "amp_enable" not in cmd:
            self._log.warning(
                "Amp enable not specified in new command, using default value: 0"
            )
            cmd["amp_enable"] = 1

        if "gain_db_tx" not in cmd:
            self._log.warning(
                "TX gain not specified in new command, using default value: 40"
            )
            cmd["gain_db_tx"] = 40

        cmd_list = self._base_cmd + [
            "-t",
            "/tmp/fifos/mod2hackrf.fifo",
            "-f",
            str(cmd["freq_hz"]),
            "-s",
            str(cmd["sample_rate_hz"]),
            "-a",
            str(cmd["amp_enable"]),
            "-x",
            str(cmd["gain_db_tx"]),
        ]

        return cmd_list
