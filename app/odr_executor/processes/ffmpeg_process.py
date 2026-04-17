import os

from typing import Any

from app.odr_executor.core.logger import base_log, TaskLoggerAdapter
from app.odr_executor.core.guard import ProcessGuard


class FFmpegGuard(ProcessGuard):

    def __init__(self, port: int) -> None:
        super().__init__(f"FFmpeg-{port}")
        self._log = TaskLoggerAdapter(base_log, {"tag": self.tag})
        self._base_cmd = ["ffmpeg"]

    def _parse_command(self, cmd: dict[str, Any]) -> list[str]:
        self._log.info("parsing command for ffmpeg process...")

        filename = cmd["filename"]
        path = "/tmp/ffmpeg"
        os.makedirs(path, exist_ok=True)
        audio_file_path = os.path.join(path, filename)
        with open(audio_file_path, "wb") as radio:
            radio.write(cmd["file_bytes"])

        cmd_list = self._base_cmd + [
            "-readrate",
            "1.06",
            "-stream_loop",
            "1",
            "-i",
            f"{audio_file_path}",
            "-acodec",
            "pcm_s16le",
            "-f",
            "s16le",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-flush_packets",
            "1",
            f"udp://192.168.112.166:{cmd['port']}?pkt_size=1316&buffer_size=65536",
        ]

        return cmd_list
