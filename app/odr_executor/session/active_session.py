from app.odr_executor.core.logger import TaskLoggerAdapter, base_log
from app.odr_executor.common.utils import ensure_fifo
from app.odr_executor.processes.audioenc_process import AudioEncGuard
from app.odr_executor.processes.padenc_process import PadEncGuard
from app.odr_executor.processes.socat_process import SocatGuard


class ActiveSession:
    def __init__(self, task_id: str, socat_port: int) -> None:
        self._socat_to_audio_fifo: str = f"/tmp/fifos/socat2audio-{task_id}.fifo"
        self._padenc_guard: PadEncGuard = PadEncGuard(task_id)
        self._audioenc_guard: AudioEncGuard = AudioEncGuard(
            task_id, self._socat_to_audio_fifo
        )
        self._socat_guard: SocatGuard = SocatGuard(
            task_id, socat_port, self._socat_to_audio_fifo
        )

        self._log = TaskLoggerAdapter(base_log, {"tag": "ActiveSession"})

    def _prepare(self) -> None:
        self._log.info("preparing active session...")
        ensure_fifo(self._socat_to_audio_fifo)

    def launch(self) -> None:
        self._log.info("launching active session...")
        self._prepare()
        self._padenc_guard.deploy()
        self._socat_guard.deploy()
        self._audioenc_guard.deploy()

    def stop(self) -> None:
        self._log.info("stopping active session...")
        self._audioenc_guard.undeploy()
        self._padenc_guard.undeploy()
        self._socat_guard.undeploy()
