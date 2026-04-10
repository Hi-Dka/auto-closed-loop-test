import os
import requests
from time import time
from typing import Literal
from uuid import uuid4

from app.scheduler.core.base_action import BaseParam, CompletionPolicy
from app.scheduler.core.logger import base_log, TaskLoggerAdapter
from app.scheduler.actions.template_action import ActionPhase, TemplateAction


log = TaskLoggerAdapter(base_log, {"tag": "ScanAction"})

DEFAULT_SCAN_ENDPOINT = "http://127.0.0.1:8000/scan"


ScanPhase = ActionPhase


class ScanParam(BaseParam):
    time_out: int = 30


class ScanAction(TemplateAction[ScanParam]):

    CALLBACK_TYPE = "scan"
    REQUEST_ID_PREFIX = "scan"
    GROUP_ID_PREFIX = "scan-group"
    SEND_COUNT = 1
    EXPECT_POLICY = CompletionPolicy.exactly(1)
    TIMEOUT_BEHAVIOR: Literal["fail_fast", "partial_ok", "continue_on_timeout"] = (
        "fail_fast"
    )
    MIN_CALLBACKS_ON_TIMEOUT = 0

    def __init__(self):
        super().__init__(ScanParam)
        self._scan_endpoint = os.getenv("SCHEDULER_SCAN_URL", DEFAULT_SCAN_ENDPOINT)

    @property
    def callback_type(self) -> str:
        return self.CALLBACK_TYPE

    @property
    def phase_timeout_seconds(self) -> float:
        return float(self._params.time_out)

    def build_phases(self) -> list[ScanPhase]:
        return [
            ScanPhase(
                name="scan-dispatch",
                send_count=self.SEND_COUNT,
                completion_policy=self.EXPECT_POLICY,
                request_id_validation_enabled=True,
                timeout_behavior=self.TIMEOUT_BEHAVIOR,
                min_callbacks_on_timeout=self.MIN_CALLBACKS_ON_TIMEOUT,
            )
        ]

    def dispatch_request(
        self, request_id: str, group_id: str, phase: ScanPhase
    ) -> bool:
        return self.post_scan(request_id=request_id, group_id=group_id, phase=phase)

    def post_scan(self, request_id: str, group_id: str, phase: ScanPhase) -> bool:
        try:
            log.info(
                f"Posting phase '{phase.name}' with request_id={request_id}, group_id={group_id}"
            )
            response = requests.post(
                self._scan_endpoint,
                timeout=5,
                json={
                    "background": True,
                    "request_id": request_id,
                    "group_id": group_id,
                    "callback_type": self.callback_type,
                    "ts": time(),
                },
            )
            response.raise_for_status()
            log.info(f"Scan POST response: {response.status_code} - {response.json()}")
            return True
        except requests.RequestException as e:
            log.error(f"Failed to post scan result: {e}")
            return False

    def _build_request_id(self) -> str:
        return f"{self.REQUEST_ID_PREFIX}-{uuid4().hex}"

    def _build_group_id(self) -> str:
        return f"{self.GROUP_ID_PREFIX}-{uuid4().hex}"
