from abc import ABC, abstractmethod
import copy
import os
import signal
import subprocess
import threading
import time
from typing import Any, TextIO
from collections.abc import Sequence

from .logger import base_log, TaskLoggerAdapter


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
                return

            self._log.info(f"Engine command: {' '.join(self._cmd)}")

            try:
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

                    stdout = process.stdout
                    if stdout is not None:
                        log_thread = threading.Thread(
                            target=self._log_reader, args=(stdout,), daemon=True
                        )
                        log_thread.start()

                    return_code = process.wait()

                if self._is_running:
                    self._restart_count += 1
                    self._log.warning(
                        f"process exited with code: {return_code}. Restarting..."
                    )
                    time.sleep(2)
                else:
                    self._log.info(
                        f"process stopped manually, exit code: {return_code}"
                    )

                self._process = None

            except (OSError, subprocess.SubprocessError) as e:
                self._log.error(
                    f"process failed to start or encountered an error: {str(e)}"
                )
                time.sleep(5)

    def _start_guard(self, cmd_list: Sequence[str]) -> None:
        if self._is_running:
            self._log.warning(
                "ProcessGuard is already running. Please stop it before restarting."
            )
            return

        self._cmd = list(cmd_list)
        self._is_running = True
        self._monitor_thread = threading.Thread(target=self._monitor, daemon=True)
        self._monitor_thread.start()
        self._log.info("ProcessGuard is starting...")

    def _stop_guard(self) -> None:
        if not self._is_running:
            self._log.warning("ProcessGuard is not running. Nothing to stop.")
            return

        self._log.info("ProcessGuard is stopping...")
        self._is_running = False

        if self._process:
            target_pid = self._process.pid

            if target_pid is not None and hasattr(os, "killpg"):
                try:
                    os.killpg(target_pid, signal.SIGTERM)
                except ProcessLookupError:
                    self._log.debug("Process group already exited before SIGTERM.")
                except OSError as exc:
                    self._log.debug(
                        f"Failed to send SIGTERM to process group: {exc}. Falling back to terminate()."
                    )
                    self._process.terminate()
            else:
                self._process.terminate()

            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._log.warning(
                    "Process failed to stop gracefully, killing it (SIGKILL)"
                )

                if target_pid is not None and hasattr(os, "killpg"):
                    try:
                        os.killpg(target_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        self._log.debug("Process group already exited before SIGKILL.")
                    except OSError as exc:
                        self._log.debug(
                            f"Failed to send SIGKILL to process group: {exc}. Falling back to kill()."
                        )
                        self._process.kill()
                else:
                    self._process.kill()

                self._process.wait(timeout=3)

            self._process = None

        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=3.0)

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

    @property
    def status(self) -> str:
        if not self._is_running:
            return "stopped"
        if self._process and self._process.poll() is None:
            return "running"
        return "restarting"

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
            "pid": self.pid,
            "restart_count": self.restart_count,
            "command": self._cmd,
            "tag": self.tag,
        }
