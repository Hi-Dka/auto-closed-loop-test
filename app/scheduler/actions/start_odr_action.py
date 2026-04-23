from time import sleep, time
from typing import Any, Literal
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
    HTTP_TIMEOUT_SECONDS = 5
    FFMPEG_HTTP_TIMEOUT_SECONDS = 30
    STOP_HTTP_TIMEOUT_SECONDS = 20

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
                name="stop-all-before-start",
                send_count=self.SEND_COUNT,
                completion_policy=self.EXPECT_POLICY,
                request_id_validation_enabled=True,
                timeout=self.phase_timeout_seconds,
                timeout_behavior=self.TIMEOUT_BEHAVIOR,
                min_callbacks_on_timeout=self.MIN_CALLBACKS_ON_TIMEOUT,
                need_callback=False,
            ),
            StartODRPhase(
                name="start-stable-session",
                send_count=self.SEND_COUNT,
                completion_policy=self.EXPECT_POLICY,
                request_id_validation_enabled=True,
                timeout=self.phase_timeout_seconds,
                timeout_behavior=self.TIMEOUT_BEHAVIOR,
                min_callbacks_on_timeout=self.MIN_CALLBACKS_ON_TIMEOUT,
                need_callback=False,  # Stable session doesn't send callbacks
                wait_time_before_dispatch=4,
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
                wait_time_before_dispatch=4,
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
                wait_time_before_dispatch=4,
            ),
        ]

    def dispatch_request(
        self, request_id: str, group_id: str, phase: StartODRPhase
    ) -> bool:
        if phase.name == "stop-all-before-start":
            return self.post_stop_all(request_id, group_id, phase)
        elif phase.name == "start-stable-session":
            return self.post_start_stable_session(request_id, group_id, phase)
        elif phase.name == "start-active-session":
            return self.post_start_active_session(request_id, group_id, phase)
        elif phase.name == "start-ffmpeg":
            return self.post_start_ffmpeg(request_id, group_id, phase)
        else:
            log.error(f"Unknown phase name '{phase.name}' for dispatching request.")
            return False

    # ------------------------------ start odr tools ----------------------------- #
    def post_stop_all(
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
                self.start_endpoint + "/all/stop",
                timeout=self.STOP_HTTP_TIMEOUT_SECONDS,
                data={**necessary_data},
            )
            response.raise_for_status()
            log.info(
                f"Stop all POST response: {response.status_code} - {response.json()}"
            )
            sleep(1)
            return True
        except requests.RequestException as e:
            log.error(f"Failed to post stop all before start: {e}")
            return False

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
                self.start_endpoint + "/stable/configure",
                timeout=self.HTTP_TIMEOUT_SECONDS,
                data={
                    **necessary_data,
                    "dabmod_mode": 1,
                    "dabmod_format": "s8",
                    "dabmod_gain": 0.8,
                    "dabmod_gainmode": "max",
                    "dabmod_rate": 2048000,
                    "hackrf_freq_hz": 227360000,
                    "hackrf_sample_rate_hz": 2048000,
                    "hackrf_amp_enable": 1,
                    "hackrf_gain_db_tx": 40,
                },
            )
            response.raise_for_status()
            log.info(
                f"Stable configure POST response: {response.status_code} - {response.json()}"
            )

            response = requests.post(
                self.start_endpoint + "/stable/start",
                timeout=self.HTTP_TIMEOUT_SECONDS,
                data={**necessary_data},
            )
            response.raise_for_status()
            log.info(
                f"Stable start POST response: {response.status_code} - {response.json()}"
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
                self.start_endpoint + "/active/configure",
                timeout=self.HTTP_TIMEOUT_SECONDS,
                data={
                    **necessary_data,
                    "port": 5656,
                    "output_port": 9000,
                    "bitrate": 64,
                    "sample_rate": 48000,
                    "channels": 2,
                    "format": "raw",
                    "audio_gain": 0,
                    "pad": 58,
                    "padenc_sleep": 10,
                },
            )
            response.raise_for_status()
            log.info(
                f"Active configure POST response: {response.status_code} - {response.json()}"
            )

            response = requests.post(
                self.start_endpoint + "/active/start",
                timeout=self.HTTP_TIMEOUT_SECONDS,
                data={**necessary_data, "port": 5656},
            )
            response.raise_for_status()
            log.info(
                f"Active start POST response: {response.status_code} - {response.json()}"
            )

            response = requests.post(
                self.start_endpoint + "/active/configure",
                timeout=self.HTTP_TIMEOUT_SECONDS,
                data={
                    **necessary_data,
                    "port": 5657,
                    "output_port": 9002,
                    "bitrate": 64,
                    "sample_rate": 48000,
                    "channels": 2,
                    "format": "raw",
                    "audio_gain": 0,
                    "pad": 58,
                    "padenc_sleep": 10,
                },
            )
            response.raise_for_status()
            log.info(
                f"Active configure POST response: {response.status_code} - {response.json()}"
            )

            response = requests.post(
                self.start_endpoint + "/active/start",
                timeout=self.HTTP_TIMEOUT_SECONDS,
                data={**necessary_data, "port": 5657},
            )
            response.raise_for_status()
            log.info(
                f"Active start POST response: {response.status_code} - {response.json()}"
            )

            return True
        except requests.RequestException as e:
            log.error(f"Failed to post start active session: {e}")
            return False

    def post_start_ffmpeg(
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
            with open(
                Path(__file__).resolve().parents[3] / "files" / "lanlianhua.wav", "rb"
            ) as f:
                response = requests.post(
                    self.start_endpoint + "/ffmpeg/configure",
                    timeout=self.FFMPEG_HTTP_TIMEOUT_SECONDS,
                    data={
                        **necessary_data,
                        "port": 5656,
                    },
                    files={"file": ("lanlianhua.wav", f, "audio/wav")},
                )
                response.raise_for_status()
                log.info(
                    f"FFmpeg configure POST response: {response.status_code} - {response.json()}"
                )

            response = requests.post(
                self.start_endpoint + "/ffmpeg/start",
                timeout=self.FFMPEG_HTTP_TIMEOUT_SECONDS,
                data={
                    **necessary_data,
                    "port": 5656,
                },
            )
            response.raise_for_status()
            log.info(
                f"FFmpeg start POST response: {response.status_code} - {response.json()}"
            )

            sleep(2)
            with open(
                Path(__file__).resolve().parents[3] / "files" / "No_Rest.wav", "rb"
            ) as f:
                response = requests.post(
                    self.start_endpoint + "/ffmpeg/configure",
                    timeout=self.FFMPEG_HTTP_TIMEOUT_SECONDS,
                    data={
                        **necessary_data,
                        "port": 5657,
                    },
                    files={"file": ("No_Rest.wav", f, "audio/wav")},
                )
                response.raise_for_status()
                log.info(
                    f"FFmpeg configure POST response: {response.status_code} - {response.json()}"
                )

            response = requests.post(
                self.start_endpoint + "/ffmpeg/start",
                timeout=self.FFMPEG_HTTP_TIMEOUT_SECONDS,
                data={
                    **necessary_data,
                    "port": 5657,
                },
            )
            response.raise_for_status()
            log.info(
                f"FFmpeg start POST response: {response.status_code} - {response.json()}"
            )
            return True
        except requests.RequestException as e:
            log.error(f"Failed to post start ffmpeg session: {e}")
            return False

    def _build_request_id(self) -> str:
        return f"{self.REQUEST_ID_PREFIX}-{uuid4().hex}"

    def _build_group_id(self) -> str:
        return f"{self.GROUP_ID_PREFIX}-{uuid4().hex}"

    def _validate_phase_callbacks(
        self, phase: ActionPhase, callbacks: list[dict[str, Any]]
    ) -> bool:
        return True
