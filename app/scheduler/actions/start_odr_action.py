from time import sleep, time
from typing import Literal
from uuid import uuid4
from pathlib import Path

import requests

from app.scheduler.core.base_action import BaseParam, CompletionPolicy
from app.scheduler.core.logger import base_log, TaskLoggerAdapter
from app.scheduler.actions.template_action import ActionPhase, TemplateAction

log = TaskLoggerAdapter(base_log, {"tag": "StartODRAction"})

DEFAULT_START_ENDPOINT = "http://127.0.0.1:8080/command/v1"


StartODRPhase = ActionPhase


class StartODRParam(BaseParam):
    url: str = DEFAULT_START_ENDPOINT


class StartODRAction(TemplateAction[StartODRParam]):

    CALLBACK_TYPE = "start-odr"
    REQUEST_ID_PREFIX = "start-odr"
    GROUP_ID_PREFIX = "start-odr-group"
    SEND_COUNT = 1
    EXPECT_POLICY = CompletionPolicy.exactly(1)
    TIMEOUT_BEHAVIOR: Literal["fail_fast", "partial_ok", "continue_on_timeout"] = (
        "fail_fast"
    )
    MIN_CALLBACKS_ON_TIMEOUT = 0

    def __init__(self):
        super().__init__(StartODRParam)

    @property
    def callback_type(self) -> str:
        return self.CALLBACK_TYPE

    @property
    def phase_timeout_seconds(self) -> float:
        return float(30)

    @property
    def start_endpoint(self) -> str:
        return str(self._params.url)

    def build_phases(self) -> list[StartODRPhase]:
        return [
            StartODRPhase(
                name="start-stable-session",
                send_count=self.SEND_COUNT,
                completion_policy=self.EXPECT_POLICY,
                request_id_validation_enabled=True,
                timeout=self.phase_timeout_seconds,
                timeout_behavior=self.TIMEOUT_BEHAVIOR,
                min_callbacks_on_timeout=self.MIN_CALLBACKS_ON_TIMEOUT,
                need_callback=False,  # Stable session doesn't send callbacks
            ),
            StartODRPhase(
                name="start-active-session",
                send_count=self.SEND_COUNT,
                completion_policy=self.EXPECT_POLICY,
                request_id_validation_enabled=True,
                timeout=self.phase_timeout_seconds,
                timeout_behavior=self.TIMEOUT_BEHAVIOR,
                min_callbacks_on_timeout=self.MIN_CALLBACKS_ON_TIMEOUT,
                need_callback=False,  # Active session doesn't send callbacks
            ),
            StartODRPhase(
                name="start-ffmpeg",
                send_count=self.SEND_COUNT,
                completion_policy=self.EXPECT_POLICY,
                request_id_validation_enabled=True,
                timeout=self.phase_timeout_seconds,
                timeout_behavior=self.TIMEOUT_BEHAVIOR,
                min_callbacks_on_timeout=self.MIN_CALLBACKS_ON_TIMEOUT,
                need_callback=False,  # FFmpeg session doesn't send callbacks
            ),
        ]

    def dispatch_request(
        self, request_id: str, group_id: str, phase: StartODRPhase
    ) -> bool:
        if phase.name == "start-stable-session":
            return self.post_start_stable_session(request_id, group_id, phase)
        elif phase.name == "start-active-session":
            return self.post_start_active_session(request_id, group_id, phase)
        elif phase.name == "start-ffmpeg":
            return self.post_start_ffmpeg(request_id, group_id, phase)
        else:
            log.error(f"Unknown phase name '{phase.name}' for dispatching request.")
            return False

    # ------------------------------ start odr tools ----------------------------- #
    def post_start_stable_session(
        self, request_id: str, group_id: str, phase: StartODRPhase
    ) -> bool:
        try:
            necessary_data = {
                "request_id": request_id,
                "group_id": group_id,
                "callback_type": self.callback_type,
                "timestamp": time(),
            }

            log.info(
                f"Posting phase '{phase.name}' with request_id={request_id}, group_id={group_id}"
            )
            response = requests.post(
                self.start_endpoint + "/launchstable",
                timeout=5,
                json=necessary_data,
            )
            response.raise_for_status()
            log.info(
                f"Start ODR POST response: {response.status_code} - {response.json()}"
            )
            return True
        except requests.RequestException as e:
            log.error(f"Failed to post start stable session: {e}")
            return False

    def post_start_active_session(
        self, request_id: str, group_id: str, phase: StartODRPhase
    ) -> bool:
        try:
            necessary_data = {
                "request_id": request_id,
                "group_id": group_id,
                "callback_type": self.callback_type,
                "timestamp": time(),
            }
            log.info(
                f"Posting phase '{phase.name}' with request_id={request_id}, group_id={group_id}"
            )
            response = requests.post(
                self.start_endpoint + "/launchactive/5656",
                timeout=5,
                json=necessary_data,
            )
            response.raise_for_status()
            log.info(
                f"Start ODR POST response: {response.status_code} - {response.json()}"
            )

            response = requests.post(
                self.start_endpoint + "/launchactive/5657",
                timeout=5,
                json=necessary_data,
            )
            response.raise_for_status()
            log.info(
                f"Start ODR POST response: {response.status_code} - {response.json()}"
            )

            sleep(2)

            response = requests.post(
                self.start_endpoint + "/audioenc/5657/update",
                timeout=5,
                json={"output_port": 9002},
            )
            response.raise_for_status()
            log.info(
                f"Start ODR POST response: {response.status_code} - {response.json()}"
            )

            return True
        except requests.RequestException as e:
            log.error(f"Failed to post start active session: {e}")
            return False

    def post_start_ffmpeg(
        self, request_id: str, group_id: str, phase: StartODRPhase
    ) -> bool:
        try:
            log.info(
                f"Posting phase '{phase.name}' with request_id={request_id}, group_id={group_id}"
            )
            sleep(2)
            with open(
                Path(__file__).resolve().parents[3] / "files" / "lanlianhua.wav", "rb"
            ) as f:
                file = {"file": ("lanlianhua.wav", f, "audio/wav")}
                response = requests.post(
                    self.start_endpoint + "/launchffmpeg/5656",
                    timeout=5,
                    files=file,
                )
                response.raise_for_status()
                log.info(
                    f"Start FFmpeg POST response: {response.status_code} - {response.json()}"
                )

            sleep(2)
            with open(
                Path(__file__).resolve().parents[3] / "files" / "No_Rest.wav", "rb"
            ) as f:
                file = {"file": ("No_Rest.wav", f, "audio/wav")}
                response = requests.post(
                    self.start_endpoint + "/launchffmpeg/5657",
                    timeout=5,
                    files=file,
                )
                response.raise_for_status()
                log.info(
                    f"Start FFmpeg POST response: {response.status_code} - {response.json()}"
                )
            return True
        except requests.RequestException as e:
            log.error(f"Failed to post start ffmpeg session: {e}")
            return False

    def _build_request_id(self) -> str:
        return f"{self.REQUEST_ID_PREFIX}-{uuid4().hex}"

    def _build_group_id(self) -> str:
        return f"{self.GROUP_ID_PREFIX}-{uuid4().hex}"
