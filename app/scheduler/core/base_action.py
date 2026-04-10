from __future__ import annotations
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
import threading
from time import monotonic, time
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T", bound="BaseParam")


class BaseParam(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CountPolicy:
    kind: str
    count: Optional[int] = None
    stop_when: Optional[Callable[[dict[str, Any]], bool]] = None
    window_seconds: Optional[float] = None

    def __init__(self, kind: str, **kwargs):
        self.kind = kind
        self.__dict__.update(kwargs)

    @classmethod
    def exactly(cls, n: int) -> CountPolicy:
        p = cls("exactly")
        p.count = n
        return p

    @classmethod
    def at_least(cls, n: int) -> CountPolicy:
        p = cls("at_least")
        p.count = n
        return p

    @classmethod
    def any_one(cls) -> CountPolicy:
        return cls("any_one")

    @classmethod
    def until(cls, stop_when: Callable[[dict[str, Any]], bool]) -> CountPolicy:
        p = cls("until")
        p.stop_when = stop_when
        return p

    @classmethod
    def time_window_collect(cls, window_seconds: float) -> CountPolicy:
        p = cls("time_window_collect")
        p.window_seconds = window_seconds
        return p


class MatchPolicy:
    kind: str
    request_ids: Optional[list[str]] = None

    def __init__(self, kind: str, **kwargs):
        self.kind = kind
        self.__dict__.update(kwargs)

    @classmethod
    def no_filter(cls) -> "MatchPolicy":
        return cls("no_filter")

    @classmethod
    def by_request_ids(cls, request_ids: list[str]) -> "MatchPolicy":
        p = cls("by_request_ids")
        p.request_ids = request_ids
        return p


@dataclass(frozen=True)
class CompletionPolicy:
    count: CountPolicy
    match: MatchPolicy = field(default_factory=MatchPolicy.no_filter)

    @classmethod
    def exactly(cls, n: int) -> CompletionPolicy:
        return cls(count=CountPolicy.exactly(n))

    @classmethod
    def at_least(cls, n: int) -> CompletionPolicy:
        return cls(count=CountPolicy.at_least(n))

    @classmethod
    def any_one(cls) -> CompletionPolicy:
        return cls(count=CountPolicy.any_one())

    @classmethod
    def until(cls, stop_when: Callable[[dict[str, Any]], bool]) -> CompletionPolicy:
        return cls(count=CountPolicy.until(stop_when))

    @classmethod
    def time_window_collect(cls, window_seconds: float) -> "CompletionPolicy":
        return cls(count=CountPolicy.time_window_collect(window_seconds))

    def with_request_ids(self, request_ids: list[str]) -> "CompletionPolicy":
        return CompletionPolicy(
            count=self.count,
            match=MatchPolicy.by_request_ids(request_ids),
        )


class BaseAction(ABC, Generic[T]):

    def __init__(self, param_model: type[T]):
        self._callback_queue: deque[dict[str, Any]] = deque()
        self._callback_condition = threading.Condition()
        self._seen_callback_keys: dict[str, float] = {}
        self._callback_ttl_seconds = 300.0
        self._param_model = param_model
        self._params: T

    @abstractmethod
    def run(self) -> bool: ...

    def parse_params(self, params: dict[str, Any]) -> None:
        self._params = self._param_model(**params)

    def _wait_for_callback(
        self,
        timeout: float = 30.0,
        callback_type: Optional[str] = None,
        request_id: Optional[str] = None,
        group_id: Optional[str] = None,
        predicate: Optional[Callable[[dict[str, Any]], bool]] = None,
    ) -> dict[str, Any]:
        deadline = monotonic() + timeout

        with self._callback_condition:
            while True:
                self._cleanup_expired_locked(now=time())
                match_index = self._find_match_index(
                    callback_type=callback_type,
                    request_id=request_id,
                    group_id=group_id,
                    predicate=predicate,
                )
                if match_index is not None:
                    callback_data = self._callback_queue[match_index]
                    del self._callback_queue[match_index]
                    return callback_data

                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError("Timed out waiting for callback data.")

                self._callback_condition.wait(timeout=remaining)

    def _wait_for_callbacks(
        self,
        expected_count: int,
        timeout: float = 30.0,
        callback_type: Optional[str] = None,
        request_id: Optional[str] = None,
        group_id: Optional[str] = None,
        predicate: Optional[Callable[[dict[str, Any]], bool]] = None,
    ) -> list[dict[str, Any]]:
        if expected_count <= 0:
            raise ValueError("expected_count must be greater than 0.")

        deadline = monotonic() + timeout
        callbacks: list[dict[str, Any]] = []
        for _ in range(expected_count):
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for callback data.")
            callbacks.append(
                self._wait_for_callback(
                    timeout=remaining,
                    callback_type=callback_type,
                    request_id=request_id,
                    group_id=group_id,
                    predicate=predicate,
                )
            )

        return callbacks

    def _wait_for_callbacks_by_policy(
        self,
        policy: CompletionPolicy,
        timeout: float = 30.0,
        callback_type: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        deadline = monotonic() + timeout

        base_kwargs: dict[str, Any] = {
            "callback_type": callback_type,
            "group_id": group_id,
        }
        match_policy: MatchPolicy = (
            policy.match if policy.match is not None else MatchPolicy.no_filter()
        )

        request_ids: list[str] | None = (
            match_policy.request_ids if match_policy.kind == "by_request_ids" else None
        )

        request_id_set: set[str] | None = set(request_ids) if request_ids else None

        # Helper to combine base kwargs with any additional overrides for specific calls
        def _make_kwargs(**overrides: Any) -> dict[str, Any]:
            kwargs = dict(base_kwargs)
            kwargs.update(overrides)
            return kwargs

        if policy.count.kind == "any_one":
            if request_id_set is not None:
                callback = self._wait_for_callback(
                    timeout=timeout,
                    predicate=lambda cb: cb.get("request_id") in request_id_set,
                    **_make_kwargs(),
                )
                return [callback]

            return [
                self._wait_for_callback(
                    timeout=timeout,
                    **_make_kwargs(),
                )
            ]

        if policy.count.kind == "exactly":
            if not policy.count.count or policy.count.count <= 0:
                raise ValueError("CountPolicy.exactly requires count > 0")

            if request_id_set is not None and request_ids is not None:
                target_count = policy.count.count
                counts_by_id: dict[str, int] = {req_id: 0 for req_id in request_ids}
                callbacks: list[dict[str, Any]] = []
                while True:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Timed out waiting for callback data.")

                    callback = self._wait_for_callback(
                        timeout=remaining,
                        predicate=lambda cb: cb.get("request_id") in request_id_set,
                        **_make_kwargs(),
                    )
                    request_id = callback.get("request_id")
                    if (
                        request_id in counts_by_id
                        and counts_by_id[request_id] < target_count
                    ):
                        counts_by_id[request_id] += 1
                        callbacks.append(callback)

                    if all(count >= target_count for count in counts_by_id.values()):
                        return callbacks

            return self._wait_for_callbacks(
                expected_count=policy.count.count,
                timeout=timeout,
                **_make_kwargs(),
            )

        if policy.count.kind == "at_least":
            if not policy.count.count or policy.count.count <= 0:
                raise ValueError("CountPolicy.at_least requires count > 0")

            if request_id_set is not None and request_ids is not None:
                target_count = policy.count.count
                counts_by_id: dict[str, int] = {req_id: 0 for req_id in request_ids}
                callbacks: list[dict[str, Any]] = []
                while True:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Timed out waiting for callback data.")

                    callback = self._wait_for_callback(
                        timeout=remaining,
                        predicate=lambda cb: cb.get("request_id") in request_id_set,
                        **_make_kwargs(),
                    )
                    callbacks.append(callback)

                    request_id = callback.get("request_id")
                    if request_id in counts_by_id:
                        counts_by_id[request_id] += 1

                    if all(count >= target_count for count in counts_by_id.values()):
                        callbacks.extend(
                            self._drain_matching_callbacks(
                                predicate=lambda cb: cb.get("request_id")
                                in request_id_set,
                                **_make_kwargs(),
                            )
                        )
                        return callbacks

            callbacks = self._wait_for_callbacks(
                expected_count=policy.count.count,
                timeout=timeout,
                **_make_kwargs(),
            )
            callbacks.extend(self._drain_matching_callbacks(**_make_kwargs()))
            return callbacks

        if policy.count.kind == "until":
            if policy.count.stop_when is None:
                raise ValueError("CountPolicy.until requires stop_when condition")

            if request_id_set is not None and request_ids is not None:
                done_ids: set[str] = set()
                callbacks: list[dict[str, Any]] = []
                while True:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Timed out waiting for callback data.")

                    callback = self._wait_for_callback(
                        timeout=remaining,
                        predicate=lambda cb: cb.get("request_id") in request_id_set,
                        **_make_kwargs(),
                    )
                    callbacks.append(callback)

                    request_id = callback.get("request_id")
                    if request_id in request_id_set and policy.count.stop_when(
                        callback
                    ):
                        done_ids.add(request_id)

                    if len(done_ids) == len(request_id_set):
                        return callbacks

            callbacks: list[dict[str, Any]] = []
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError("Timed out waiting for callback data.")
                callback = self._wait_for_callback(
                    timeout=remaining,
                    **_make_kwargs(),
                )
                callbacks.append(callback)
                if policy.count.stop_when(callback):
                    return callbacks

        if policy.count.kind == "time_window_collect":
            if not policy.count.window_seconds or policy.count.window_seconds <= 0:
                raise ValueError(
                    "CountPolicy.time_window_collect requires window_seconds > 0"
                )

            if request_id_set is not None and request_ids is not None:
                window_seconds = policy.count.window_seconds
                callbacks: list[dict[str, Any]] = []
                window_start_by_id: dict[str, float] = {}

                while True:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Timed out waiting for callback data.")

                    all_windows_expired = True
                    for req_id in request_ids:
                        if req_id not in window_start_by_id:
                            all_windows_expired = False
                            break
                        window_end = window_start_by_id[req_id] + window_seconds
                        if monotonic() < window_end:
                            all_windows_expired = False
                            break
                    if all_windows_expired:
                        return callbacks

                    callback = self._wait_for_callback(
                        timeout=remaining,
                        predicate=lambda cb: cb.get("request_id") in request_id_set,
                        **_make_kwargs(),
                    )
                    callbacks.append(callback)
                    request_id = callback.get("request_id")

                    if request_id and request_id not in window_start_by_id:
                        window_start_by_id[request_id] = monotonic()

            first = self._wait_for_callback(
                timeout=timeout,
                **_make_kwargs(),
            )
            callbacks = [first]
            window_deadline = monotonic() + policy.count.window_seconds

            while True:
                remaining = window_deadline - monotonic()
                if remaining <= 0:
                    break
                callback = self._pop_matching_callback(**_make_kwargs())
                if callback is None:
                    with self._callback_condition:
                        self._callback_condition.wait(timeout=remaining)
                    continue
                callbacks.append(callback)

            return callbacks

        raise ValueError(f"Unsupported count policy kind: {policy.count.kind}")

    def notify_callback(
        self, data: dict[str, Any], callback_type: Optional[str] = None
    ) -> None:
        callback_data = self._normalize_callback_data(data, callback_type)
        dedupe_key = self._build_dedupe_key(callback_data)
        now = time()

        with self._callback_condition:
            self._cleanup_expired_locked(now=now)
            if dedupe_key in self._seen_callback_keys:
                return

            self._seen_callback_keys[dedupe_key] = now
            self._callback_queue.append(callback_data)
            self._callback_condition.notify_all()

    def _find_match_index(
        self,
        callback_type: Optional[str],
        request_id: Optional[str],
        group_id: Optional[str],
        predicate: Optional[Callable[[dict[str, Any]], bool]],
    ) -> Optional[int]:
        for index, callback_data in enumerate(self._callback_queue):
            if callback_type and callback_data.get("callback_type") != callback_type:
                continue
            if request_id and callback_data.get("request_id") != request_id:
                continue
            if group_id and callback_data.get("group_id") != group_id:
                continue
            if predicate and not predicate(callback_data):
                continue
            return index

        return None

    def _pop_matching_callback(
        self,
        callback_type: Optional[str] = None,
        request_id: Optional[str] = None,
        group_id: Optional[str] = None,
        predicate: Optional[Callable[[dict[str, Any]], bool]] = None,
    ) -> Optional[dict[str, Any]]:
        with self._callback_condition:
            self._cleanup_expired_locked(now=time())
            match_index = self._find_match_index(
                callback_type=callback_type,
                request_id=request_id,
                group_id=group_id,
                predicate=predicate,
            )
            if match_index is None:
                return None

            callback_data = self._callback_queue[match_index]
            del self._callback_queue[match_index]
            return callback_data

    def _drain_matching_callbacks(
        self,
        callback_type: Optional[str] = None,
        request_id: Optional[str] = None,
        group_id: Optional[str] = None,
        predicate: Optional[Callable[[dict[str, Any]], bool]] = None,
    ) -> list[dict[str, Any]]:
        drained: list[dict[str, Any]] = []
        while True:
            callback = self._pop_matching_callback(
                callback_type=callback_type,
                request_id=request_id,
                group_id=group_id,
                predicate=predicate,
            )
            if callback is None:
                break
            drained.append(callback)
        return drained

    def _normalize_callback_data(
        self, data: dict[str, Any], callback_type: Optional[str]
    ) -> dict[str, Any]:
        callback_data = dict(data)

        normalized_callback_type = (
            callback_type
            or callback_data.get("callback_type")
            or callback_data.get("type")
            or "unknown"
        )
        normalized_status = callback_data.get("status", "unknown")
        normalized_payload = callback_data.get("payload", dict(callback_data))
        normalized_ts = callback_data.get("ts", time())

        callback_data["callback_type"] = normalized_callback_type
        callback_data["status"] = normalized_status
        callback_data["payload"] = normalized_payload
        callback_data["ts"] = normalized_ts

        # Ensure request_id and group_id keys exist for easier processing later,
        # even if they are None
        callback_data.setdefault("request_id", None)
        callback_data.setdefault("group_id", None)

        return callback_data

    def _build_dedupe_key(self, callback_data: dict[str, Any]) -> str:
        callback_id = callback_data.get("callback_id")
        if callback_id:
            return f"callback_id:{callback_id}"

        request_id = callback_data.get("request_id")
        seq = callback_data.get("seq")
        if request_id is not None and seq is not None:
            return f"request_seq:{request_id}:{seq}"

        callback_type = callback_data.get("callback_type")
        status = callback_data.get("status")
        ts = callback_data.get("ts")
        return f"fallback:{request_id}:{callback_type}:{status}:{ts}"

    def _cleanup_expired_locked(self, now: float) -> None:
        expire_before = now - self._callback_ttl_seconds

        self._callback_queue = deque(
            callback
            for callback in self._callback_queue
            if float(callback.get("ts", now)) >= expire_before
        )

        expired_keys = [
            key
            for key, seen_ts in self._seen_callback_keys.items()
            if seen_ts < expire_before
        ]
        for key in expired_keys:
            del self._seen_callback_keys[key]
