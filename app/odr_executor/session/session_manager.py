from typing import Optional

from app.odr_executor.session.stable_session import StableSession
from app.odr_executor.session.active_session import ActiveSession
from app.odr_executor.processes.ffmpeg_process import FFmpegGuard
from app.odr_executor.core.logger import base_log, TaskLoggerAdapter
from app.odr_executor.common.singleton import singleton


@singleton
class SessionManager:
    _active_ports = set()

    def __init__(self) -> None:
        self._stable_session = StableSession()
        self._active_sessions: dict[int, ActiveSession] = {}
        self._ffmpeg_guard: dict[int, FFmpegGuard] = {}
        self._log = TaskLoggerAdapter(base_log, {"tag": "SessionManager"})

    @classmethod
    def check_port(cls, port: int) -> bool:
        if port in cls._active_ports:
            return False
        cls._active_ports.add(port)
        return True

    @classmethod
    def release_port(cls, port: int) -> None:
        cls._active_ports.discard(port)

    def launch_stable_session(self) -> None:
        self._log.info("launching stable session...")
        self._stable_session.launch()

    def stop_stable_session(self, wait: bool = True, timeout: float = 8.0) -> None:
        self._log.info("stopping stable session...")
        self._stable_session.stop()
        if wait and not self._wait_stable_stopped(timeout=timeout):
            raise RuntimeError("Timed out waiting for stable session to stop.")

    def launch_active_session(self, socat_port: int) -> None:
        self._log.info(f"launching active session for task {socat_port}...")

        if not self.check_port(socat_port):
            self._log.error(f"Port {socat_port} is already in use.")
            return None

        active_session = ActiveSession(str(socat_port), socat_port)
        active_session.launch()
        self._active_sessions[socat_port] = active_session

    def stop_active_session(
        self,
        socat_port: int,
        release_port: bool = True,
        wait: bool = True,
        timeout: float = 8.0,
    ) -> None:
        if release_port:
            self.release_port(socat_port)

        if socat_port in self._active_sessions:
            self._log.info(f"stopping active session for task {socat_port}...")
            self._active_sessions[socat_port].stop()
            if wait and not self._wait_active_stopped(socat_port, timeout=timeout):
                raise RuntimeError(
                    f"Timed out waiting for active session {socat_port} to stop."
                )
        else:
            self._log.warning(f"active session for task {socat_port} not found.")

    def stop_all_active_sessions(self, wait: bool = True, timeout: float = 8.0) -> None:
        self._log.info("stopping all active sessions...")
        for port in list(self._active_sessions.keys()):
            self.stop_active_session(port, wait=False)

        if wait and not self._wait_all_active_stopped(timeout=timeout):
            raise RuntimeError("Timed out waiting for all active sessions to stop.")

    def launch_all_active_sessions(self) -> None:
        self._log.info("launching all active sessions...")
        for port in list(self._active_sessions.keys()):
            self.launch_active_session(port)

    def dispatch(self, target: str, data: dict, port: Optional[int] = None) -> None:
        self._log.info(
            f"Dispatching command to target: {target}, port: {port}, data: {data}"
        )

        is_update_cmd = False
        is_stable_update = False
        is_active_update = False
        is_ffmpeg_update = False

        if target == "ffmpeg":
            if not port or port not in self._ffmpeg_guard:
                self._log.error(f"Invalid port {port} for FFmpeg guard update.")
                raise ValueError(f"Invalid port {port} for FFmpeg guard update.")

            guard = self._ffmpeg_guard[port]
            guard.update_command(data)
            is_update_cmd = True
            is_ffmpeg_update = True

        if target in ["dabmux", "dabmod", "hackrf"]:
            processor = getattr(self._stable_session, f"_{target}_guard", None)
            if processor:
                processor.update_command(data)
                is_update_cmd = True
                is_stable_update = True

        if target in ["audioenc", "padenc", "socat"]:
            if not port or port not in self._active_sessions:
                self._log.error(f"Invalid port {port} for target {target}.")
                raise ValueError(f"Invalid port {port} for target {target}.")

            session = self._active_sessions[port]
            processor = getattr(session, f"_{target}_guard", None)
            if processor:
                processor.update_command(data)
                is_update_cmd = True
                is_active_update = True

        if not is_update_cmd:
            self._log.error(f"Unknown target type: {target}")
            raise ValueError(f"Unknown target type: {target}")

        if is_ffmpeg_update:
            self._log.info("FFmpeg command updated, restarting all FFmpeg guards...")
            for guard in self._ffmpeg_guard.values():
                guard.undeploy()
                guard.deploy()

        if is_stable_update:
            self.stop_stable_session(wait=True, timeout=8.0)
            self.launch_stable_session()

        if is_active_update and port is not None:
            session = self._active_sessions[port]
            session.stop()
            if not self._wait_active_stopped(port, timeout=8.0):
                raise RuntimeError(
                    f"Timed out waiting for active session {port} to stop."
                )
            session.launch()

        self._log.info(f"Command dispatched successfully to {target} on port {port}.")
        return None

    def stop_ffmpeg_guards(self, guard_id: int):
        guard = self._ffmpeg_guard.get(guard_id)
        if guard:
            guard.undeploy()
            guard.wait_until_stopped(timeout=8.0)
            del self._ffmpeg_guard[guard_id]
            return True
        return False

    def launch_ffmpeg_guard(self, port: int, command_data: dict) -> None:
        if port in self._ffmpeg_guard:
            self._log.warning(f"FFmpeg guard already exists for port {port}, skipping.")
            return

        guard = FFmpegGuard(port)
        guard.update_command(command_data)
        guard.deploy()
        self._ffmpeg_guard[port] = guard

    def _stable_guards(self):
        guards = [
            getattr(self._stable_session, "_dabmux_guard", None),
            getattr(self._stable_session, "_dabmod_guard", None),
            getattr(self._stable_session, "_hackrf_guard", None),
        ]
        return [guard for guard in guards if guard is not None]

    def _active_guards(self, port: int):
        session = self._active_sessions[port]
        guards = [
            getattr(session, "_padenc_guard", None),
            getattr(session, "_socat_guard", None),
            getattr(session, "_audioenc_guard", None),
        ]
        return [guard for guard in guards if guard is not None]

    def _wait_stable_stopped(self, timeout: float = 8.0) -> bool:
        guards = self._stable_guards()
        wait_results = [guard.wait_until_stopped(timeout=timeout) for guard in guards]
        if not all(wait_results):
            not_stopped = [
                guard.tag
                for guard, ok in zip(guards, wait_results, strict=False)
                if not ok
            ]
            self._log.error(f"Stable guards not fully stopped in time: {not_stopped}")
            return False
        return True

    def _wait_active_stopped(self, port: int, timeout: float = 8.0) -> bool:
        guards = self._active_guards(port)
        wait_results = [guard.wait_until_stopped(timeout=timeout) for guard in guards]
        if not all(wait_results):
            not_stopped = [
                guard.tag
                for guard, ok in zip(guards, wait_results, strict=False)
                if not ok
            ]
            self._log.error(
                f"Active guards for port {port} not fully stopped in time: {not_stopped}"
            )
            return False
        return True

    def _wait_all_active_stopped(self, timeout: float = 8.0) -> bool:
        for port in self._active_sessions.keys():
            if not self._wait_active_stopped(port, timeout=timeout):
                return False
        return True


session_manager = SessionManager()
