import base64
import binascii
import io
import math
import os
from time import time
from typing import Any, Literal, Optional
from uuid import uuid4

import requests

from app.scheduler.core.base_action import BaseParam, CompletionPolicy
from app.scheduler.core.logger import base_log, TaskLoggerAdapter
from app.scheduler.actions.template_action import ActionPhase, TemplateAction

from app.scheduler.actions.shared.constants import (
    DEFAULT_ENDPOINT,
    SELECT_LIST,
)


log = TaskLoggerAdapter(base_log, {"tag": "SelectAction"})

SelectPhase = ActionPhase


class SelectParam(BaseParam):
    time_out: int = 60


DYNAMIC_LABELS = ["PadEnc-5656", "PadEnc-5657"]
SLIDE_SHOWS_PATH = [
    "/media/padenc/sls-PadEnc-5656/5656.png",
    "/media/padenc/sls-PadEnc-5657/5657.png",
]
SLIDE_SHOW_PHASH_MAX_DISTANCE = 10

phase_to_index = {
    "select-dispatch-1": 0,
    "select-dispatch-2": 1,
}


class SelectAction(TemplateAction[SelectParam]):

    CALLBACK_TYPE = "select"
    REQUEST_ID_PREFIX = "select"
    GROUP_ID_PREFIX = "select-group"
    SEND_COUNT = 1
    EXPECT_POLICY = CompletionPolicy.at_least(2)
    TIMEOUT_BEHAVIOR: Literal["fail_fast", "partial_ok", "continue_on_timeout"] = (
        "fail_fast"
    )
    MIN_CALLBACKS_ON_TIMEOUT = 0

    def __init__(self):
        super().__init__(SelectParam)
        self._endpoint = os.getenv("DEFAULT_ENDPOINT", DEFAULT_ENDPOINT)

    @property
    def callback_type(self) -> str:
        return self.CALLBACK_TYPE

    @property
    def phase_timeout_seconds(self) -> float:
        return float(self._params.time_out)

    def build_phases(self) -> list[SelectPhase]:
        log.info(
            f"Building select phases with timeout={self.phase_timeout_seconds}, phash_threshold={SLIDE_SHOW_PHASH_MAX_DISTANCE}"
        )
        return [
            SelectPhase(
                name="select-dispatch-1",
                send_count=self.SEND_COUNT,
                completion_policy=CompletionPolicy.until(
                    self._build_select_completion_stop_when(select_index=0)
                ),
                request_id_validation_enabled=True,
                timeout=self.phase_timeout_seconds,
                timeout_behavior=self.TIMEOUT_BEHAVIOR,
                min_callbacks_on_timeout=self.MIN_CALLBACKS_ON_TIMEOUT,
            ),
            SelectPhase(
                name="select-dispatch-2",
                send_count=self.SEND_COUNT,
                completion_policy=CompletionPolicy.until(
                    self._build_select_completion_stop_when(select_index=1)
                ),
                request_id_validation_enabled=True,
                timeout=self.phase_timeout_seconds,
                timeout_behavior=self.TIMEOUT_BEHAVIOR,
                min_callbacks_on_timeout=self.MIN_CALLBACKS_ON_TIMEOUT,
            ),
        ]

    def dispatch_request(
        self, request_id: str, group_id: str, phase: SelectPhase
    ) -> bool:

        select_index = phase_to_index.get(phase.name)
        if select_index is None:
            log.error(f"Unknown phase name '{phase.name}' for select dispatch")
            return False

        return self._post_select(
            request_id=request_id,
            group_id=group_id,
            phase=phase,
            select_index=select_index,
        )

    def _post_select(
        self,
        request_id: str,
        group_id: str,
        phase: SelectPhase,
        select_index: int,
    ) -> bool:
        try:
            necessary_data = {
                "request_id": request_id,
                "group_id": group_id,
                "callback_type": self.callback_type,
                "timestamp": time(),
            }

            select_data = self._normalize_select_data(SELECT_LIST[select_index])

            log.info(
                f"Posting phase '{phase.name}' with request_id={request_id}, group_id={group_id}, select_index={select_index}, payload={select_data}"
            )
            payload = {**necessary_data, **select_data}

            response = requests.post(
                self._endpoint + "/select", timeout=5, json=payload
            )
            response.raise_for_status()
            log.info(
                f"Select Service POST response: {response.status_code} - {response.json()}"
            )
            return True

        except (IndexError, requests.RequestException) as e:
            log.error(f"Failed to post select request (index={select_index}): {e}")
            return False

    def _normalize_select_data(self, select_data: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(select_data)

        service_id = self._to_int(normalized.get("service_id"))
        component_id = self._to_int(normalized.get("component_id"))
        frequency = self._to_int(normalized.get("frequency"))

        if service_id is not None:
            normalized["service_id"] = service_id
        if component_id is not None:
            normalized["component_id"] = component_id
        if frequency is not None:
            normalized["frequency"] = frequency

        return normalized

    def _build_request_id(self) -> str:
        return f"{self.REQUEST_ID_PREFIX}-{uuid4().hex}"

    def _build_group_id(self) -> str:
        return f"{self.GROUP_ID_PREFIX}-{uuid4().hex}"

    def _validate_phase_callbacks(
        self, phase: ActionPhase, callbacks: list[dict[str, Any]]
    ) -> bool:
        if not callbacks:
            log.error(f"No callbacks received for phase '{phase.name}'")
            return False

        select_index = phase_to_index.get(phase.name)
        if select_index is None:
            log.error(
                f"Unknown phase name '{phase.name}' for select callback validation"
            )
            return False

        expected_dynamic_label = DYNAMIC_LABELS[select_index]
        expected_slide_show_phash = self._read_expected_slide_show_phash(select_index)
        if expected_slide_show_phash is None:
            log.error(
                f"Unable to load expected slide_show pHash for phase '{phase.name}'"
            )
            return False

        check_sls_valid = False
        check_dls_valid = False

        log.info(
            f"Start validating phase '{phase.name}' callbacks, count={len(callbacks)}, expected_dynamic_label={expected_dynamic_label}, phash_threshold={SLIDE_SHOW_PHASH_MAX_DISTANCE}"
        )

        for callback_index, callback in enumerate(callbacks, start=1):
            log.info(
                f"Validating callback {callback_index}/{len(callbacks)} for phase '{phase.name}': "
                f"status={callback.get('status')}, request_id={callback.get('request_id')}, group_id={callback.get('group_id')}"
            )

            payload = callback.get("payload")
            if payload is None:
                payload = callback

            if not isinstance(payload, dict):
                log.error("Select callback payload must be an object")
                return False

            callback_payload_type = payload.get("type")
            callback_data = payload.get("data")
            log.info(
                f"Phase '{phase.name}' callback {callback_index}/{len(callbacks)} parsed: callback_type={callback_payload_type}, keys={list(payload.keys())}, data_keys={list(callback_data.keys()) if isinstance(callback_data, dict) else type(callback_data).__name__}"
            )
            if not isinstance(callback_data, dict):
                log.warning(
                    f"Ignoring callback {callback_index}/{len(callbacks)} for phase '{phase.name}': payload.data is not an object"
                )
                continue

            if callback_payload_type == "dynamic_label":
                callback_dynamic_label_raw = callback_data.get("data")
                callback_dynamic_label_length = callback_data.get("length")
                callback_dynamic_label = self._normalize_dynamic_label(
                    callback_dynamic_label_raw
                )
                log.info(
                    f"Phase '{phase.name}' dynamic_label candidate: expected='{expected_dynamic_label}', raw='{callback_dynamic_label_raw}', normalized='{callback_dynamic_label}', length={callback_dynamic_label_length}"
                )
                if callback_dynamic_label == expected_dynamic_label:
                    check_dls_valid = True
                    log.info(
                        f"Dynamic label matched for phase '{phase.name}': {callback_dynamic_label}"
                    )
                else:
                    log.warning(
                        f"Dynamic label mismatch for phase '{phase.name}': expected '{expected_dynamic_label}', normalized '{callback_dynamic_label}'"
                    )
                continue

            if callback_payload_type == "slide_show":
                encoded_data = callback_data.get("data")
                encoded_len = (
                    len(encoded_data) if isinstance(encoded_data, str) else None
                )
                log.info(
                    f"Phase '{phase.name}' slide_show candidate received: encoded_len={encoded_len}"
                )
                callback_slide_show_bytes = self._decode_base64_to_bytes(encoded_data)
                if callback_slide_show_bytes is None:
                    log.error(
                        f"Invalid slide_show base64 data for phase '{phase.name}'"
                    )
                    return False

                callback_slide_show_phash = self._compute_phash_from_bytes(
                    callback_slide_show_bytes
                )
                if callback_slide_show_phash is None:
                    log.warning(
                        f"Unable to compute pHash from slide_show payload for phase '{phase.name}', continue waiting"
                    )
                    continue

                phash_distance = self._hamming_distance(
                    callback_slide_show_phash, expected_slide_show_phash
                )
                log.info(
                    f"Phase '{phase.name}' slide_show pHash computed: actual={callback_slide_show_phash}, expected={expected_slide_show_phash}, distance={phash_distance}"
                )
                if phash_distance <= SLIDE_SHOW_PHASH_MAX_DISTANCE:
                    check_sls_valid = True
                    log.info(
                        f"Slide show matched by pHash for phase '{phase.name}', distance={phash_distance}"
                    )
                else:
                    log.warning(
                        f"Slide show pHash mismatch for phase '{phase.name}', distance={phash_distance}, threshold={SLIDE_SHOW_PHASH_MAX_DISTANCE}; continue waiting for valid frame"
                    )
                continue

            log.info(
                f"Ignoring non-target select callback type '{callback_payload_type}' for phase '{phase.name}'"
            )

        if not check_dls_valid:
            log.error(f"Dynamic label callback missing for phase '{phase.name}'")
            return False
        if not check_sls_valid:
            log.error(f"Slide show callback missing for phase '{phase.name}'")
            return False

        log.info(
            f"Phase '{phase.name}' callback validation passed: dynamic_label and slide_show both matched"
        )
        return True

    def _validate_single_select_callback(
        self, callback: dict[str, Any], phase: SelectPhase
    ) -> bool:
        payload = callback.get("payload")
        if payload is None:
            payload = callback

        if not isinstance(payload, dict):
            log.error("Select callback payload must be an object")
            return False

        select_index = phase_to_index.get(phase.name)
        if select_index is None:
            log.error(
                f"Unknown phase name '{phase.name}' for select callback validation"
            )
            return False
        expected_data = self._normalize_select_data(SELECT_LIST[select_index])
        if (
            expected_data.get("service_id") != payload.get("service_id")
            or expected_data.get("component_id") != payload.get("component_id")
            or expected_data.get("frequency") != payload.get("frequency")
        ):
            log.error(f"Select callback data mismatch for phase '{phase.name}'")
            return False

        log.info("Select callback validated successfully")
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

    def _read_expected_slide_show_phash(self, select_index: int) -> Optional[int]:
        try:
            with open(SLIDE_SHOWS_PATH[select_index], "rb") as image_file:
                expected_bytes = image_file.read()
            return self._compute_phash_from_bytes(expected_bytes)
        except (IndexError, OSError) as e:
            log.error(
                f"Failed to read expected slide show for index={select_index}: {e}"
            )
            return None

    def _decode_base64_to_bytes(self, data: Any) -> Optional[bytes]:
        if not isinstance(data, str):
            return None

        try:
            return base64.b64decode(data, validate=True)
        except (ValueError, binascii.Error):
            return None

    def _compute_phash_from_bytes(self, image_bytes: bytes) -> Optional[int]:
        try:
            from PIL import Image

            with Image.open(io.BytesIO(image_bytes)) as image:
                gray = image.convert("L").resize((32, 32))
                pixels_raw = list(gray.tobytes())
        except (OSError, ValueError):
            return None

        if len(pixels_raw) != 32 * 32:
            return None

        pixels = [
            [float(pixels_raw[row * 32 + col]) for col in range(32)]
            for row in range(32)
        ]

        coeffs: list[float] = []
        for u in range(8):
            for v in range(8):
                c_u = 1 / math.sqrt(2) if u == 0 else 1.0
                c_v = 1 / math.sqrt(2) if v == 0 else 1.0
                total = 0.0
                for x in range(32):
                    for y in range(32):
                        total += (
                            pixels[x][y]
                            * math.cos(((2 * x + 1) * u * math.pi) / 64)
                            * math.cos(((2 * y + 1) * v * math.pi) / 64)
                        )
                coeffs.append(0.25 * c_u * c_v * total)

        non_dc = coeffs[1:]
        median = sorted(non_dc)[len(non_dc) // 2]

        bits = 0
        for coeff in coeffs:
            bits = (bits << 1) | (1 if coeff > median else 0)
        return bits

    def _hamming_distance(self, hash_a: int, hash_b: int) -> int:
        return (hash_a ^ hash_b).bit_count()

    def _normalize_dynamic_label(self, value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return value.rstrip("\x00").strip()

    def _build_select_completion_stop_when(self, select_index: int):
        seen_dynamic_label = False
        seen_slide_show = False
        expected_dynamic_label = DYNAMIC_LABELS[select_index]
        expected_slide_show_phash = self._read_expected_slide_show_phash(select_index)
        phase_name = next(
            (name for name, index in phase_to_index.items() if index == select_index),
            f"select-index-{select_index}",
        )

        def _stop_when(callback: dict[str, Any]) -> bool:
            nonlocal seen_dynamic_label, seen_slide_show

            if expected_slide_show_phash is None:
                return False

            payload = callback.get("payload")
            if payload is None:
                payload = callback
            if not isinstance(payload, dict):
                return False

            callback_data = payload.get("data")
            if not isinstance(callback_data, dict):
                return False

            callback_type = payload.get("type")
            log.info(
                f"Phase '{phase_name}' stop_when evaluating callback_type={callback_type}, seen_dynamic_label={seen_dynamic_label}, seen_slide_show={seen_slide_show}"
            )
            if callback_type == "dynamic_label":
                callback_dynamic_label_raw = callback_data.get("data")
                callback_dynamic_label_length = callback_data.get("length")
                callback_dynamic_label = self._normalize_dynamic_label(
                    callback_dynamic_label_raw
                )
                log.info(
                    f"Phase '{phase_name}' stop_when dynamic_label: expected='{expected_dynamic_label}', raw='{callback_dynamic_label_raw}', normalized='{callback_dynamic_label}', length={callback_dynamic_label_length}"
                )
                if callback_dynamic_label == expected_dynamic_label:
                    seen_dynamic_label = True
                    log.info(
                        f"Phase '{phase_name}' stop_when matched dynamic_label='{callback_dynamic_label}'"
                    )
            elif callback_type == "slide_show":
                encoded_data = callback_data.get("data")
                callback_slide_show_bytes = self._decode_base64_to_bytes(encoded_data)
                if callback_slide_show_bytes is not None:
                    callback_slide_show_phash = self._compute_phash_from_bytes(
                        callback_slide_show_bytes
                    )
                    if callback_slide_show_phash is not None:
                        phash_distance = self._hamming_distance(
                            callback_slide_show_phash, expected_slide_show_phash
                        )
                        log.info(
                            f"Phase '{phase_name}' stop_when slide_show pHash distance={phash_distance}, threshold={SLIDE_SHOW_PHASH_MAX_DISTANCE}"
                        )
                        if phash_distance <= SLIDE_SHOW_PHASH_MAX_DISTANCE:
                            seen_slide_show = True
                            log.info(
                                f"Phase '{phase_name}' stop_when matched slide_show by pHash"
                            )

            done = seen_dynamic_label and seen_slide_show
            if done:
                log.info(
                    f"Phase '{phase_name}' stop_when satisfied; phase can complete"
                )
            return done

        return _stop_when
