from app.odr_executor.core.logger import base_log, TaskLoggerAdapter
from app.odr_executor.core.guard import ProcessGuard
from typing import Any


class AudioEncGuard(ProcessGuard):
    def __init__(self, task_id: str, fifo: str) -> None:
        super().__init__(f"AudioEnc-{task_id}")
        self._base_cmd = ["odr-audioenc"]
        self._fifo = fifo
        self._task_id = task_id
        self._log = TaskLoggerAdapter(base_log, {"tag": self.tag})

    def _parse_command(self, cmd: dict[str, Any]) -> list[str]:

        self._log.info("parsing command for audio encoder...")

        if "output_port" not in cmd:
            self._log.warning(
                "Port not specified in new command, using default value: 9000"
            )
            cmd["output_port"] = 9000

        if "bitrate" not in cmd:
            self._log.warning(
                "Bitrate not specified in new command, using default value: 64"
            )
            cmd["bitrate"] = 64
        if "sample_rate" not in cmd:
            self._log.warning(
                "Sample rate not specified in new command, using default value: 48000"
            )
            cmd["sample_rate"] = 48000

        if "channels" not in cmd:
            self._log.warning(
                "Channels not specified in new command, using default value: 2"
            )
            cmd["channels"] = 2

        if "format" not in cmd:
            self._log.warning(
                "Format not specified in new command, using default value: raw"
            )
            cmd["format"] = "raw"
        if "audio_gain" not in cmd:
            self._log.warning(
                "Audio gain not specified in new command, using default value: 0"
            )
            cmd["audio_gain"] = 0

        if "pad" not in cmd:
            self._log.warning(
                "Pad not specified in new command, using default value: 58"
            )
            cmd["pad"] = 58

        if int(cmd["bitrate"]) % 8 != 0:
            self._log.error("Bitrate must be a multiple of 8")
            raise ValueError("Bitrate must be a multiple of 8")

        if cmd["sample_rate"] not in [24000, 32000, 48000]:
            self._log.error("Sample rate must be one of 24000, 32000, or 48000")
            raise ValueError("Sample rate must be one of 24000, 32000, or 48000")

        cmd_list = self._base_cmd + ["-i", self._fifo]
        cmd_list += [
            "-o",
            f"tcp://localhost:{cmd['output_port']}",
            "-b",
            str(cmd["bitrate"]),
            "-r",
            str(cmd["sample_rate"]),
            "-c",
            str(cmd["channels"]),
            "-f",
            str(cmd["format"]),
            "-g",
            str(cmd["audio_gain"]),
            "-p",
            str(cmd["pad"]),
            "-P",
            f"PadEnc-{self._task_id}.sock",
        ]

        return cmd_list
