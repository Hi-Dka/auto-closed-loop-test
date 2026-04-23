from typing import Any, Optional

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

    def has_active_session(self, port: int) -> bool:
        return port in self._active_sessions

    def has_ffmpeg_guard(self, port: int) -> bool:
        return port in self._ffmpeg_guard

    def snapshot(self) -> dict[str, Any]:
        stable = {guard.tag: guard.snapshot() for guard in self._stable_guards()}
        active = {
            str(port): {
                guard.tag: guard.snapshot() for guard in self._active_guards(port)
            }
            for port in self._active_sessions.keys()
        }
        ffmpeg = {
            str(port): guard.snapshot() for port, guard in self._ffmpeg_guard.items()
        }

        return {
            "stable": stable,
            "active": active,
            "ffmpeg": ffmpeg,
            "active_ports": sorted(list(self._active_ports)),
        }

    def _summarize_command_data(self, data: dict) -> dict[str, object]:
        summary: dict[str, object] = {}
        for key, value in data.items():
            if isinstance(value, (bytes, bytearray)):
                summary[key] = f"<{type(value).__name__}: {len(value)} bytes>"
            else:
                summary[key] = value
        return summary

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
            raise RuntimeError(f"Port {socat_port} is already in use.")

        active_session = ActiveSession(str(socat_port), socat_port)
        active_session.launch()
        self._active_sessions[socat_port] = active_session

    def _ensure_active_session(self, socat_port: int) -> ActiveSession:
        session = self._active_sessions.get(socat_port)
        if session is None:
            self._log.info(
                f"Active session for task {socat_port} not found, creating it before apply."
            )
            session = ActiveSession(str(socat_port), socat_port)
            self._active_sessions[socat_port] = session
        return session

    def _restart_active_session(
        self,
        socat_port: int,
        *,
        is_new_session: bool,
        timeout: float = 8.0,
    ) -> None:
        session = self._active_sessions[socat_port]
        session.stop()
        if not self._wait_active_stopped(socat_port, timeout=timeout):
            raise RuntimeError(
                f"Timed out waiting for active session {socat_port} to stop."
            )

        if is_new_session and not self.check_port(socat_port):
            raise RuntimeError(f"Port {socat_port} is already in use.")

        session.launch()

    def stop_active_session(
        self,
        socat_port: int,
        release_port: bool = True,
        wait: bool = True,
        timeout: float = 8.0,
    ) -> None:
        if socat_port in self._active_sessions:
            self._log.info(f"stopping active session for task {socat_port}...")
            self._active_sessions[socat_port].stop()
            if wait and not self._wait_active_stopped(socat_port, timeout=timeout):
                raise RuntimeError(
                    f"Timed out waiting for active session {socat_port} to stop."
                )
            if release_port:
                self.release_port(socat_port)
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

    def apply_all_active_sessions(self) -> None:
        self._log.info("applying all active sessions...")
        for port in list(self._active_sessions.keys()):
            self.stop_active_session(port)
            self.launch_active_session(port)

    def apply_active_session(
        self,
        socat_port: int,
        audioenc_data: dict | None = None,
        padenc_data: dict | None = None,
        socat_data: dict | None = None,
    ) -> None:
        self._log.info(f"applying active session for task {socat_port}...")

        is_new_session = socat_port not in self._active_sessions
        session = self._ensure_active_session(socat_port)

        session.apply(
            audioenc_data=audioenc_data,
            padenc_data=padenc_data,
            socat_data=socat_data,
        )
        self._restart_active_session(socat_port, is_new_session=is_new_session)

    def _dispatch_ffmpeg_update(self, data: dict, port: Optional[int]) -> bool:
        if not port or port not in self._ffmpeg_guard:
            self._log.error(f"Invalid port {port} for FFmpeg guard update.")
            raise ValueError(f"Invalid port {port} for FFmpeg guard update.")

        ffmpeg_port = int(port)
        guard = self._ffmpeg_guard[ffmpeg_port]
        if guard.command_equals(data):
            self._log.info(
                f"FFmpeg guard for port {ffmpeg_port} already has the same command, skipping restart."
            )
            return True

        guard.update_command(data)
        self._log.info(
            f"FFmpeg command updated, restarting guard on port {ffmpeg_port}..."
        )
        self._ffmpeg_guard[ffmpeg_port].deploy()
        return True

    def _dispatch_stable_update(self, target: str, data: dict) -> bool:
        processor = getattr(self._stable_session, f"_{target}_guard", None)
        if processor is None:
            return False

        processor.update_command(data)
        self.stop_stable_session(wait=True, timeout=8.0)
        self.launch_stable_session()
        return True

    def _dispatch_active_update(
        self, target: str, data: dict, port: Optional[int]
    ) -> bool:
        if not port:
            self._log.error(f"Invalid port {port} for target {target}.")
            raise ValueError(f"Invalid port {port} for target {target}.")

        is_new_session = port not in self._active_sessions
        session = self._ensure_active_session(port)
        processor = getattr(session, f"_{target}_guard", None)
        if processor is None:
            return False

        processor.update_command(data)
        self._restart_active_session(port, is_new_session=is_new_session)
        return True

    def dispatch(self, target: str, data: dict, port: Optional[int] = None) -> None:
        self._log.info(
            f"Dispatching command to target: {target}, port: {port}, data: {self._summarize_command_data(data)}"
        )

        handled = False

        if target == "ffmpeg":
            handled = self._dispatch_ffmpeg_update(data=data, port=port)
        elif target in ["dabmux", "dabmod", "hackrf"]:
            handled = self._dispatch_stable_update(target=target, data=data)
        elif target in ["audioenc", "padenc", "socat"]:
            handled = self._dispatch_active_update(target=target, data=data, port=port)

        if not handled:
            self._log.error(f"Unknown target type: {target}")
            raise ValueError(f"Unknown target type: {target}")

        self._log.info(f"Command dispatched successfully to {target} on port {port}.")
        return None

    def stop_ffmpeg_guards(self, port: int) -> bool:
        guard = self._ffmpeg_guard.get(port)
        if guard:
            guard.disable_restart()
            guard.undeploy()
            guard.wait_until_stopped(timeout=8.0)
            del self._ffmpeg_guard[port]
            return True
        return False

    def stop_all_ffmpeg_guards(self, timeout: float = 8.0) -> bool:
        if not self._ffmpeg_guard:
            self._log.info("No FFmpeg guards to stop.")
            return True

        self._log.info("stopping all ffmpeg guards...")
        all_stopped = True
        for port in list(self._ffmpeg_guard.keys()):
            guard = self._ffmpeg_guard.get(port)
            if guard is None:
                continue

            guard.disable_restart()
            guard.undeploy()
            if not guard.wait_until_stopped(timeout=timeout):
                self._log.error(
                    f"FFmpeg guard for port {port} not fully stopped in time"
                )
                all_stopped = False

            del self._ffmpeg_guard[port]

        return all_stopped

    def launch_ffmpeg_guard(self, port: int, command_data: dict) -> bool:
        if port in self._ffmpeg_guard:
            self._log.warning(f"FFmpeg guard already exists for port {port}, skipping.")
            return False

        guard = FFmpegGuard(port)
        guard.update_command(command_data)
        guard.deploy()
        self._ffmpeg_guard[port] = guard
        return True

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
