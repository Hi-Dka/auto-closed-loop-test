from abc import ABC, abstractmethod
import copy
from enum import Enum
import os
import signal
import subprocess
import threading
import time
from typing import Any, TextIO
from collections.abc import Sequence

from .logger import base_log, TaskLoggerAdapter


class GuardLifecycleState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    RESTARTING = "restarting"
    FAILED = "failed"


class ProcessGuard(ABC):
    def __init__(self, tag: str):
        self.tag = tag
        self._log = TaskLoggerAdapter(base_log, {"tag": tag})

        self._process: subprocess.Popen[str] | None = None
        self._is_running = False
        self._cmd: list[str] = []
        self._cmd_dict: dict[str, Any] = {}
        self._monitor_thread: threading.Thread | None = None
        self._restart_count = 0
        self._lifecycle_state: GuardLifecycleState = GuardLifecycleState.STOPPED
        self._allow_restart = True
        self._stop_event = threading.Event()

    def _terminate_process(self, process: subprocess.Popen[str]) -> None:
        target_pid = process.pid

        if target_pid is not None and hasattr(os, "killpg"):
            try:
                os.killpg(target_pid, signal.SIGTERM)
            except ProcessLookupError:
                self._log.debug("Process group already exited before SIGTERM.")
            except OSError as exc:
                self._log.debug(
                    f"Failed to send SIGTERM to process group: {exc}. Falling back to terminate()."
                )
                process.terminate()
        else:
            process.terminate()

        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._log.warning("Process failed to stop gracefully, killing it (SIGKILL)")

            if target_pid is not None and hasattr(os, "killpg"):
                try:
                    os.killpg(target_pid, signal.SIGKILL)
                except ProcessLookupError:
                    self._log.debug("Process group already exited before SIGKILL.")
                except OSError as exc:
                    self._log.debug(
                        f"Failed to send SIGKILL to process group: {exc}. Falling back to kill()."
                    )
                    process.kill()
            else:
                process.kill()

            process.wait(timeout=3)

    def _log_reader(self, pipe: TextIO) -> None:
        try:
            with pipe:
                for line in iter(pipe.readline, ""):
                    if line:
                        self._log.info(line.strip())
        except ValueError:
            self._log.debug("STDOUT pipe closed, log reader exiting.")

    def _monitor(self) -> None:
        while self._is_running:
            if not self._cmd:
                self._log.error("Engine command is empty, cannot start process.")
                self._is_running = False
                self._lifecycle_state = GuardLifecycleState.FAILED
                return

            self._log.info(f"Engine command: {' '.join(self._cmd)}")

            try:
                self._lifecycle_state = GuardLifecycleState.STARTING
                with subprocess.Popen(
                    self._cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True,
                    start_new_session=True,
                ) as process:
                    self._process = process
                    self._lifecycle_state = GuardLifecycleState.RUNNING

                    if self._stop_event.is_set() or not self._is_running:
                        self._terminate_process(process)
                        return_code = process.returncode
                        self._process = None
                        self._lifecycle_state = GuardLifecycleState.STOPPED
                        self._log.info(
                            f"process stopped manually, exit code: {return_code}"
                        )
                        break

                    stdout = process.stdout
                    if stdout is not None:
                        log_thread = threading.Thread(
                            target=self._log_reader, args=(stdout,), daemon=True
                        )
                        log_thread.start()

                    return_code = process.wait()

                if self._is_running and self._allow_restart:
                    self._restart_count += 1
                    self._lifecycle_state = GuardLifecycleState.RESTARTING
                    self._log.warning(
                        f"process exited with code: {return_code}. Restarting..."
                    )
                    if self._stop_event.wait(2):
                        break
                else:
                    self._lifecycle_state = GuardLifecycleState.STOPPED
                    self._log.info(
                        f"process stopped manually, exit code: {return_code}"
                    )

                self._process = None

            except (OSError, subprocess.SubprocessError) as e:
                self._lifecycle_state = GuardLifecycleState.FAILED
                self._log.error(
                    f"process failed to start or encountered an error: {str(e)}"
                )
                if self._stop_event.wait(5):
                    break

        self._lifecycle_state = GuardLifecycleState.STOPPED

    def _start_guard(self, cmd_list: Sequence[str]) -> None:
        if self._is_running:
            self._log.warning(
                "ProcessGuard is already running. Please stop it before restarting."
            )
            return

        self._cmd = list(cmd_list)
        self._is_running = True
        self._allow_restart = True
        self._stop_event.clear()
        self._lifecycle_state = GuardLifecycleState.STARTING
        self._monitor_thread = threading.Thread(target=self._monitor, daemon=True)
        self._monitor_thread.start()
        self._log.info("ProcessGuard is starting...")

    def _stop_guard(self) -> None:
        if not self._is_running:
            self._log.warning("ProcessGuard is not running. Nothing to stop.")
            self._lifecycle_state = GuardLifecycleState.STOPPED
            return

        self._log.info("ProcessGuard is stopping...")
        self._is_running = False
        self._allow_restart = False
        self._stop_event.set()
        self._lifecycle_state = GuardLifecycleState.STOPPING

        if self._process:
            self._terminate_process(self._process)
            self._process = None

        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=3.0)

        if self._monitor_thread and self._monitor_thread.is_alive():
            self._log.warning("Monitor thread did not exit before timeout.")

        self._lifecycle_state = GuardLifecycleState.STOPPED
        self._log.info("ProcessGuard has been stopped.")

    @abstractmethod
    def _parse_command(self, cmd: dict[str, Any]) -> list[str]:
        pass

    def deploy(self) -> None:
        command_list = self._parse_command(self._cmd_dict)

        self._stop_guard()
        self._start_guard(command_list)

    def undeploy(self) -> None:
        self._stop_guard()

    def disable_restart(self) -> None:
        self._allow_restart = False

    def wait_until_stopped(
        self, timeout: float = 5.0, poll_interval: float = 0.1
    ) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            process_exited = self._process is None or self._process.poll() is not None
            monitor_exited = (
                self._monitor_thread is None or not self._monitor_thread.is_alive()
            )
            if not self._is_running and process_exited and monitor_exited:
                return True
            time.sleep(poll_interval)
        return False

    def update_command(self, cmd: dict[str, Any]) -> None:
        self._log.info("Updating command for ProcessGuard...")
        self._cmd_dict = copy.deepcopy(cmd)

    def command_equals(self, cmd: dict[str, Any]) -> bool:
        return self._cmd_dict == cmd

    @property
    def status(self) -> str:
        return self._lifecycle_state.value

    @property
    def pid(self) -> int | None:
        if self._process is None:
            return None
        return self._process.pid

    @property
    def restart_count(self) -> int:
        return self._restart_count

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "lifecycle_state": self.status,
            "pid": self.pid,
            "restart_count": self.restart_count,
            "command": self._cmd,
            "tag": self.tag,
        }
