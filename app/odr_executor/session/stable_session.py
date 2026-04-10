from app.odr_executor.core.logger import TaskLoggerAdapter, base_log
from app.odr_executor.common.utils import ensure_fifo
from app.odr_executor.processes.dabmod_process import DabModGuard
from app.odr_executor.processes.dabmux_process import DabMuxGuard
from app.odr_executor.processes.hackrf_process import HackRFGuard


class StableSession:
    def __init__(self) -> None:
        self._dabmux_guard: DabMuxGuard = DabMuxGuard()
        self._dabmod_guard: DabModGuard = DabModGuard()
        self._hackrf_guard: HackRFGuard = HackRFGuard()
        self._log = TaskLoggerAdapter(base_log, {"tag": "StableSession"})

    def _prepare(self) -> None:
        self._log.info("preparing stable session...")
        mod2hackrf: str = "/tmp/fifos/mod2hackrf.fifo"
        mux2mod: str = "/tmp/fifos/mux2mod.fifo"
        ensure_fifo(mod2hackrf)
        ensure_fifo(mux2mod)

    def launch(self) -> None:
        self._log.info("launching stable session...")
        self._prepare()
        self._dabmux_guard.deploy()
        self._dabmod_guard.deploy()
        self._hackrf_guard.deploy()

    def stop(self) -> None:
        self._log.info("stopping stable session...")

        self._dabmux_guard.undeploy()
        self._dabmod_guard.undeploy()
        self._hackrf_guard.undeploy()
