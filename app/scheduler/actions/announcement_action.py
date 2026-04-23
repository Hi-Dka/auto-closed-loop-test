from time import time
from typing import Any, Literal
from uuid import uuid4

import asyncio
import telnetlib3
import requests

from app.scheduler.core.base_action import BaseParam, CompletionPolicy
from app.scheduler.core.logger import base_log, TaskLoggerAdapter
from app.scheduler.actions.template_action import ActionPhase, TemplateAction

from app.scheduler.actions.shared.constants import (
    DEFAULT_ENDPOINT,
)

TELNET_HOST = "127.0.0.1"
TELNET_PORT = 12721

log = TaskLoggerAdapter(base_log, {"tag": "SelectAction"})

AnnouncementPhase = ActionPhase


class AnnouncementParam(BaseParam):
    time_out: int = 30


class AnnouncementAction(TemplateAction[AnnouncementParam]):

    CALLBACK_TYPE = "announcement"
    REQUEST_ID_PREFIX = "announcement"
    GROUP_ID_PREFIX = "announcement-group"
    SEND_COUNT = 1
    EXPECT_POLICY = CompletionPolicy.exactly(1)
    TIMEOUT_BEHAVIOR: Literal["fail_fast", "partial_ok", "continue_on_timeout"] = (
        "fail_fast"
    )
    MIN_CALLBACKS_ON_TIMEOUT = 0

    def __init__(self):
        super().__init__(AnnouncementParam)
        self._endpoint = DEFAULT_ENDPOINT

    @property
    def callback_type(self) -> str:
        return self.CALLBACK_TYPE

    @property
    def phase_timeout_seconds(self) -> float:
        return float(self._params.time_out)

    def build_phases(self) -> list[AnnouncementPhase]:
        return [
            AnnouncementPhase(
                name="traffic-active-1",
                send_count=self.SEND_COUNT,
                completion_policy=self.EXPECT_POLICY,
                request_id_validation_enabled=True,
                timeout=self.phase_timeout_seconds,
                timeout_behavior=self.TIMEOUT_BEHAVIOR,
                min_callbacks_on_timeout=self.MIN_CALLBACKS_ON_TIMEOUT,
            ),
            AnnouncementPhase(
                name="traffic-active-0",
                send_count=self.SEND_COUNT,
                completion_policy=self.EXPECT_POLICY,
                request_id_validation_enabled=True,
                timeout=self.phase_timeout_seconds,
                timeout_behavior=self.TIMEOUT_BEHAVIOR,
                min_callbacks_on_timeout=self.MIN_CALLBACKS_ON_TIMEOUT,
            ),
        ]

    def dispatch_request(
        self, request_id: str, group_id: str, phase: ActionPhase
    ) -> bool:
        if phase.name == "traffic-active-1":
            self._traffic_post(request_id, group_id, phase)
            return self._telnet_send(active=1)
        elif phase.name == "traffic-active-0":
            self._traffic_post(request_id, group_id, phase)
            return self._telnet_send(active=0)
        else:
            log.error(f"Unknown phase name: {phase.name}")
            return False

    def _traffic_post(
        self, request_id: str, group_id: str, _: AnnouncementPhase
    ) -> bool:
        payload = {
            "request_id": request_id,
            "group_id": group_id,
            "callback_type": self.callback_type,
            "timestamp": time(),
        }
        try:
            response = requests.post(
                self._endpoint + "/announcement",
                json=payload,
                timeout=5,
            )
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            log.error(f"Failed to send announcement traffic: {e}")
            return False

    def _telnet_send(self, active: int) -> bool:
        try:

            async def _send() -> None:
                _, writer = await telnetlib3.open_connection(TELNET_HOST, TELNET_PORT)
                command: str = f"set traffic_announcement active {active}\n"
                log.info(f"Sending telnet command: {command.strip()}")
                if isinstance(writer, telnetlib3.stream_writer.TelnetWriterUnicode):
                    writer.write(command)
                else:
                    writer.write(command.encode())
                await writer.drain()
                writer.close()

            asyncio.run(_send())
            return True
        except (
            ConnectionRefusedError,
            TimeoutError,
            asyncio.TimeoutError,
            BrokenPipeError,
            EOFError,
        ) as e:
            log.error(f"Failed to send telnet command: {e}")
            return False

    def _validate_phase_callbacks(
        self, phase: ActionPhase, callbacks: list[dict[str, Any]]
    ) -> bool:
        return True  # No additional validation beyond completion policy for announcement action

    def _build_request_id(self) -> str:
        return f"{self.REQUEST_ID_PREFIX}-{uuid4().hex}"

    def _build_group_id(self) -> str:
        return f"{self.GROUP_ID_PREFIX}-{uuid4().hex}"
