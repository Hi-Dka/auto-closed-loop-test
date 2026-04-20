import os
import requests
from time import time
from typing import Any, Literal, Optional
from uuid import uuid4

from app.scheduler.core.base_action import BaseParam, CompletionPolicy
from app.scheduler.core.logger import base_log, TaskLoggerAdapter
from app.scheduler.actions.template_action import ActionPhase, TemplateAction


log = TaskLoggerAdapter(base_log, {"tag": "ScanAction"})

DEFAULT_SCAN_ENDPOINT = "http://127.0.0.1:8000/scan"

SERVER_LIST = [
    {"label": "music srv one", "id": "0x4daa"},
    {"label": "music srv two", "id": "0x4dab"},
]

ENSEMBLE_ID = "0x4ffe"
ENSEMBLE_LABEL = "OpenDigitalRadio"
ENSEMBLE_SERVICES = SERVER_LIST

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
                timeout=self.phase_timeout_seconds,
                timeout_behavior=self.TIMEOUT_BEHAVIOR,
                min_callbacks_on_timeout=self.MIN_CALLBACKS_ON_TIMEOUT,
            )
        ]

    def _validate_phase_callbacks(
        self, phase: ScanPhase, callbacks: list[dict[str, Any]]
    ) -> bool:
        log.info(
            f"Start validating phase '{phase.name}' callbacks, count={len(callbacks)}"
        )
        return self._validate_scan_callbacks(callbacks)

    def dispatch_request(
        self, request_id: str, group_id: str, phase: ScanPhase
    ) -> bool:
        return self._post_scan(request_id=request_id, group_id=group_id, phase=phase)

    def _post_scan(self, request_id: str, group_id: str, phase: ScanPhase) -> bool:
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
                    "timestamp": time(),
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

    def _validate_scan_callbacks(self, callbacks: list[dict[str, Any]]) -> bool:
        if not callbacks:
            log.error("No callbacks received for scan phase")
            return False

        log.info(f"Scan callback validation started, callbacks={len(callbacks)}")

        for index, callback in enumerate(callbacks, start=1):
            log.info(
                f"Validating callback {index}/{len(callbacks)}: "
                f"status={callback.get('status')}, request_id={callback.get('request_id')}, group_id={callback.get('group_id')}"
            )
            if not self._validate_single_callback(callback):
                log.error(f"Callback {index}/{len(callbacks)} validation failed")
                return False

        log.info("All scan callbacks validated successfully")
        return True

    def _validate_single_callback(self, callback: dict[str, Any]) -> bool:
        status = str(callback.get("status", "")).lower()
        if status not in {"success", "ok"}:
            log.error(
                f"Scan callback status is not successful: {callback.get('status')}"
            )
            return False

        payload = callback.get("payload")
        if not isinstance(payload, dict):
            log.error("Scan callback payload must be an object")
            return False

        ensembles = payload.get("ensembles")
        if not isinstance(ensembles, list):
            log.error("Scan callback payload.ensembles must be a list")
            return False

        ensemble_count = payload.get("ensemble_count")
        if isinstance(ensemble_count, int) and ensemble_count != len(ensembles):
            log.error(
                "Scan callback ensemble_count does not match actual ensembles length: "
                f"{ensemble_count} != {len(ensembles)}"
            )
            return False

        expected_ensemble_id = self._to_int(ENSEMBLE_ID)
        target_ensemble = self._find_target_ensemble(
            ensembles=ensembles,
            expected_ensemble_id=expected_ensemble_id,
            expected_ensemble_label=ENSEMBLE_LABEL,
        )
        if target_ensemble is None:
            log.error(
                "Target ensemble not found in scan payload: "
                f"id={ENSEMBLE_ID}, label={ENSEMBLE_LABEL}"
            )
            return False

        log.info(
            "Target ensemble matched: "
            f"id={target_ensemble.get('ensemble_id')}, "
            f"label={target_ensemble.get('ensemble_label')}"
        )

        services = target_ensemble.get("services")
        if not isinstance(services, list):
            log.error("Target ensemble services must be a list")
            return False

        service_count = target_ensemble.get("service_count")
        if isinstance(service_count, int) and service_count != len(services):
            log.error(
                "Target ensemble service_count does not match actual services length: "
                f"{service_count} != {len(services)}"
            )
            return False

        if not self._contains_expected_services(services):
            return False

        log.info(
            "Target ensemble services validated successfully: "
            f"expected={len(ENSEMBLE_SERVICES)}, actual={len(services)}"
        )

        return True

    def _find_target_ensemble(
        self,
        ensembles: list[Any],
        expected_ensemble_id: Optional[int],
        expected_ensemble_label: str,
    ) -> Optional[dict[str, Any]]:
        for ensemble in ensembles:
            if not isinstance(ensemble, dict):
                continue

            ensemble_id = self._to_int(ensemble.get("ensemble_id"))
            ensemble_label = str(ensemble.get("ensemble_label", "")).strip()

            id_match = (
                expected_ensemble_id is not None and ensemble_id == expected_ensemble_id
            )
            label_match = ensemble_label == expected_ensemble_label
            if id_match and label_match:
                return ensemble

        return None

    def _contains_expected_services(self, services: list[Any]) -> bool:
        normalized_actual: set[tuple[Optional[int], str]] = set()
        for service in services:
            if not isinstance(service, dict):
                continue
            service_id = self._to_int(service.get("service_id"))
            service_label = str(service.get("service_label", "")).strip().lower()
            normalized_actual.add((service_id, service_label))

        for expected in ENSEMBLE_SERVICES:
            expected_id = self._to_int(expected.get("id"))
            expected_label = str(expected.get("label", "")).strip().lower()

            if (expected_id, expected_label) not in normalized_actual:
                log.error(
                    "Expected service not found in target ensemble: "
                    f"id={expected.get('id')}, label={expected.get('label')}"
                )
                return False

            log.info(
                "Expected service found in target ensemble: "
                f"id={expected.get('id')}, label={expected.get('label')}"
            )

        return True

    def _to_int(self, value: Any) -> Optional[int]:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            raw = value.strip().lower()
            if raw.startswith("0x"):
                try:
                    return int(raw, 16)
                except ValueError:
                    return None
            try:
                return int(raw)
            except ValueError:
                return None
        return None
