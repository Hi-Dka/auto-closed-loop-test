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


class CallbackStore:
    """Owns callback queue lifecycle: normalize, dedupe, match, wait, and cleanup."""

    def __init__(self, ttl_seconds: float = 300.0):
        self._queue: deque[dict[str, Any]] = deque()
        self._condition = threading.Condition()
        self._seen_keys: dict[str, float] = {}
        self._ttl_seconds = ttl_seconds

    def wait_for_one(
        self,
        timeout: float = 30.0,
        callback_type: Optional[str] = None,
        request_id: Optional[str] = None,
        group_id: Optional[str] = None,
        predicate: Optional[Callable[[dict[str, Any]], bool]] = None,
    ) -> dict[str, Any]:
        deadline = monotonic() + timeout

        with self._condition:
            while True:
                self._cleanup_expired_locked(now=time())
                match_index = self._find_match_index(
                    callback_type=callback_type,
                    request_id=request_id,
                    group_id=group_id,
                    predicate=predicate,
                )
                if match_index is not None:
                    callback_data = self._queue[match_index]
                    del self._queue[match_index]
                    return callback_data

                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError("Timed out waiting for callback data.")
                self._condition.wait(timeout=remaining)

    def wait_for_many(
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
                self.wait_for_one(
                    timeout=remaining,
                    callback_type=callback_type,
                    request_id=request_id,
                    group_id=group_id,
                    predicate=predicate,
                )
            )
        return callbacks

    def notify(self, data: dict[str, Any], callback_type: Optional[str] = None) -> None:
        callback_data = self._normalize_callback_data(data, callback_type)
        now = time()
        callback_data["received_at"] = now
        dedupe_key = self._build_dedupe_key(callback_data)

        with self._condition:
            self._cleanup_expired_locked(now=now)
            if dedupe_key in self._seen_keys:
                return
            self._seen_keys[dedupe_key] = now
            self._queue.append(callback_data)
            self._condition.notify_all()

    def pop_matching(
        self,
        callback_type: Optional[str] = None,
        request_id: Optional[str] = None,
        group_id: Optional[str] = None,
        predicate: Optional[Callable[[dict[str, Any]], bool]] = None,
    ) -> Optional[dict[str, Any]]:
        with self._condition:
            self._cleanup_expired_locked(now=time())
            match_index = self._find_match_index(
                callback_type=callback_type,
                request_id=request_id,
                group_id=group_id,
                predicate=predicate,
            )
            if match_index is None:
                return None

            callback_data = self._queue[match_index]
            del self._queue[match_index]
            return callback_data

    def drain_matching(
        self,
        callback_type: Optional[str] = None,
        request_id: Optional[str] = None,
        group_id: Optional[str] = None,
        predicate: Optional[Callable[[dict[str, Any]], bool]] = None,
    ) -> list[dict[str, Any]]:
        drained: list[dict[str, Any]] = []
        while True:
            callback = self.pop_matching(
                callback_type=callback_type,
                request_id=request_id,
                group_id=group_id,
                predicate=predicate,
            )
            if callback is None:
                return drained
            drained.append(callback)

    def wait_on_condition(self, timeout: float) -> None:
        with self._condition:
            self._condition.wait(timeout=timeout)

    def _find_match_index(
        self,
        callback_type: Optional[str],
        request_id: Optional[str],
        group_id: Optional[str],
        predicate: Optional[Callable[[dict[str, Any]], bool]],
    ) -> Optional[int]:
        for index, callback_data in enumerate(self._queue):
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

    def _normalize_callback_data(
        self, data: dict[str, Any], callback_type: Optional[str]
    ) -> dict[str, Any]:
        callback_data = dict(data)
        callback_data["callback_type"] = (
            callback_type
            or callback_data.get("callback_type")
            or callback_data.get("type")
            or "unknown"
        )
        callback_data["status"] = callback_data.get("status", "unknown")
        callback_data["payload"] = callback_data.get("payload", dict(callback_data))
        callback_data["timestamp"] = callback_data.get("timestamp", time())
        callback_data.setdefault("received_at", None)
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
        timestamp = callback_data.get("timestamp")
        return f"fallback:{request_id}:{callback_type}:{status}:{timestamp}"

    def _cleanup_expired_locked(self, now: float) -> None:
        expire_before = now - self._ttl_seconds

        self._queue = deque(
            callback
            for callback in self._queue
            if float(callback.get("received_at") or callback.get("timestamp", now))
            >= expire_before
        )

        expired_keys = [
            key for key, seen_ts in self._seen_keys.items() if seen_ts < expire_before
        ]
        for key in expired_keys:
            del self._seen_keys[key]


class CallbackPolicyExecutor:
    """Executes CompletionPolicy against a callback store."""

    def __init__(self, callback_store: CallbackStore):
        self._store = callback_store

    def wait_by_policy(
        self,
        policy: CompletionPolicy,
        timeout: float = 30.0,
        callback_type: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
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

        if policy.count.kind == "any_one":
            return self._handle_any_one(
                timeout=timeout,
                base_kwargs=base_kwargs,
                request_id_set=request_id_set,
            )

        if policy.count.kind == "exactly":
            return self._handle_exactly(
                policy=policy,
                timeout=timeout,
                base_kwargs=base_kwargs,
                request_ids=request_ids,
                request_id_set=request_id_set,
            )

        if policy.count.kind == "at_least":
            return self._handle_at_least(
                policy=policy,
                timeout=timeout,
                base_kwargs=base_kwargs,
                request_ids=request_ids,
                request_id_set=request_id_set,
            )

        if policy.count.kind == "until":
            return self._handle_until(
                policy=policy,
                timeout=timeout,
                base_kwargs=base_kwargs,
                request_ids=request_ids,
                request_id_set=request_id_set,
            )

        if policy.count.kind == "time_window_collect":
            return self._handle_time_window_collect(
                policy=policy,
                timeout=timeout,
                base_kwargs=base_kwargs,
                request_ids=request_ids,
                request_id_set=request_id_set,
            )

        raise ValueError(f"Unsupported count policy kind: {policy.count.kind}")

    def _make_kwargs(
        self, base_kwargs: dict[str, Any], **overrides: Any
    ) -> dict[str, Any]:
        kwargs = dict(base_kwargs)
        kwargs.update(overrides)
        return kwargs

    def _handle_any_one(
        self,
        timeout: float,
        base_kwargs: dict[str, Any],
        request_id_set: Optional[set[str]],
    ) -> list[dict[str, Any]]:
        if request_id_set is not None:
            callback = self._store.wait_for_one(
                timeout=timeout,
                predicate=lambda cb: cb.get("request_id") in request_id_set,
                **self._make_kwargs(base_kwargs),
            )
            return [callback]
        return [
            self._store.wait_for_one(
                timeout=timeout,
                **self._make_kwargs(base_kwargs),
            )
        ]

    def _handle_exactly(
        self,
        policy: CompletionPolicy,
        timeout: float,
        base_kwargs: dict[str, Any],
        request_ids: Optional[list[str]],
        request_id_set: Optional[set[str]],
    ) -> list[dict[str, Any]]:
        if not policy.count.count or policy.count.count <= 0:
            raise ValueError("CountPolicy.exactly requires count > 0")

        if request_id_set is not None and request_ids is not None:
            deadline = monotonic() + timeout
            target_count = policy.count.count
            counts_by_id: dict[str, int] = {req_id: 0 for req_id in request_ids}
            callbacks: list[dict[str, Any]] = []
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError("Timed out waiting for callback data.")

                callback = self._store.wait_for_one(
                    timeout=remaining,
                    predicate=lambda cb: cb.get("request_id") in request_id_set,
                    **self._make_kwargs(base_kwargs),
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

        return self._store.wait_for_many(
            expected_count=policy.count.count,
            timeout=timeout,
            **self._make_kwargs(base_kwargs),
        )

    def _handle_at_least(
        self,
        policy: CompletionPolicy,
        timeout: float,
        base_kwargs: dict[str, Any],
        request_ids: Optional[list[str]],
        request_id_set: Optional[set[str]],
    ) -> list[dict[str, Any]]:
        if not policy.count.count or policy.count.count <= 0:
            raise ValueError("CountPolicy.at_least requires count > 0")

        if request_id_set is not None and request_ids is not None:
            deadline = monotonic() + timeout
            target_count = policy.count.count
            counts_by_id: dict[str, int] = {req_id: 0 for req_id in request_ids}
            callbacks: list[dict[str, Any]] = []
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError("Timed out waiting for callback data.")

                callback = self._store.wait_for_one(
                    timeout=remaining,
                    predicate=lambda cb: cb.get("request_id") in request_id_set,
                    **self._make_kwargs(base_kwargs),
                )
                callbacks.append(callback)

                request_id = callback.get("request_id")
                if request_id in counts_by_id:
                    counts_by_id[request_id] += 1

                if all(count >= target_count for count in counts_by_id.values()):
                    callbacks.extend(
                        self._store.drain_matching(
                            predicate=lambda cb: cb.get("request_id") in request_id_set,
                            **self._make_kwargs(base_kwargs),
                        )
                    )
                    return callbacks

        callbacks = self._store.wait_for_many(
            expected_count=policy.count.count,
            timeout=timeout,
            **self._make_kwargs(base_kwargs),
        )
        callbacks.extend(self._store.drain_matching(**self._make_kwargs(base_kwargs)))
        return callbacks

    def _handle_until(
        self,
        policy: CompletionPolicy,
        timeout: float,
        base_kwargs: dict[str, Any],
        request_ids: Optional[list[str]],
        request_id_set: Optional[set[str]],
    ) -> list[dict[str, Any]]:
        if policy.count.stop_when is None:
            raise ValueError("CountPolicy.until requires stop_when condition")

        stop_when = policy.count.stop_when

        if request_id_set is not None and request_ids is not None:
            deadline = monotonic() + timeout
            done_ids: set[str] = set()
            callbacks: list[dict[str, Any]] = []
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError("Timed out waiting for callback data.")

                callback = self._store.wait_for_one(
                    timeout=remaining,
                    predicate=lambda cb: cb.get("request_id") in request_id_set,
                    **self._make_kwargs(base_kwargs),
                )
                callbacks.append(callback)

                request_id = callback.get("request_id")
                if request_id in request_id_set and stop_when(callback):
                    done_ids.add(request_id)

                if len(done_ids) == len(request_id_set):
                    return callbacks

        deadline = monotonic() + timeout
        callbacks: list[dict[str, Any]] = []
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for callback data.")
            callback = self._store.wait_for_one(
                timeout=remaining,
                **self._make_kwargs(base_kwargs),
            )
            callbacks.append(callback)
            if stop_when(callback):
                return callbacks

    def _handle_time_window_collect(
        self,
        policy: CompletionPolicy,
        timeout: float,
        base_kwargs: dict[str, Any],
        request_ids: Optional[list[str]],
        request_id_set: Optional[set[str]],
    ) -> list[dict[str, Any]]:
        if not policy.count.window_seconds or policy.count.window_seconds <= 0:
            raise ValueError(
                "CountPolicy.time_window_collect requires window_seconds > 0"
            )

        window_seconds = policy.count.window_seconds

        if request_id_set is not None and request_ids is not None:
            deadline = monotonic() + timeout
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

                callback = self._store.wait_for_one(
                    timeout=remaining,
                    predicate=lambda cb: cb.get("request_id") in request_id_set,
                    **self._make_kwargs(base_kwargs),
                )
                callbacks.append(callback)
                request_id = callback.get("request_id")
                if request_id and request_id not in window_start_by_id:
                    window_start_by_id[request_id] = monotonic()

        first = self._store.wait_for_one(
            timeout=timeout, **self._make_kwargs(base_kwargs)
        )
        callbacks = [first]
        window_deadline = monotonic() + window_seconds

        while True:
            remaining = window_deadline - monotonic()
            if remaining <= 0:
                break
            callback = self._store.pop_matching(**self._make_kwargs(base_kwargs))
            if callback is None:
                self._store.wait_on_condition(timeout=remaining)
                continue
            callbacks.append(callback)
        return callbacks


class BaseAction(ABC, Generic[T]):

    def __init__(self, param_model: type[T]):
        self._param_model = param_model
        self._params: T
        self._callback_store = CallbackStore(ttl_seconds=300.0)
        self._policy_executor = CallbackPolicyExecutor(self._callback_store)

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
        return self._callback_store.wait_for_one(
            timeout=timeout,
            callback_type=callback_type,
            request_id=request_id,
            group_id=group_id,
            predicate=predicate,
        )

    def _wait_for_callbacks(
        self,
        expected_count: int,
        timeout: float = 30.0,
        callback_type: Optional[str] = None,
        request_id: Optional[str] = None,
        group_id: Optional[str] = None,
        predicate: Optional[Callable[[dict[str, Any]], bool]] = None,
    ) -> list[dict[str, Any]]:
        return self._callback_store.wait_for_many(
            expected_count=expected_count,
            timeout=timeout,
            callback_type=callback_type,
            request_id=request_id,
            group_id=group_id,
            predicate=predicate,
        )

    def _wait_for_callbacks_by_policy(
        self,
        policy: CompletionPolicy,
        timeout: float = 30.0,
        callback_type: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        return self._policy_executor.wait_by_policy(
            policy=policy,
            timeout=timeout,
            callback_type=callback_type,
            group_id=group_id,
        )

    def notify_callback(
        self, data: dict[str, Any], callback_type: Optional[str] = None
    ) -> None:
        self._callback_store.notify(data=data, callback_type=callback_type)

    def _pop_matching_callback(
        self,
        callback_type: Optional[str] = None,
        request_id: Optional[str] = None,
        group_id: Optional[str] = None,
        predicate: Optional[Callable[[dict[str, Any]], bool]] = None,
    ) -> Optional[dict[str, Any]]:
        return self._callback_store.pop_matching(
            callback_type=callback_type,
            request_id=request_id,
            group_id=group_id,
            predicate=predicate,
        )

    def _drain_matching_callbacks(
        self,
        callback_type: Optional[str] = None,
        request_id: Optional[str] = None,
        group_id: Optional[str] = None,
        predicate: Optional[Callable[[dict[str, Any]], bool]] = None,
    ) -> list[dict[str, Any]]:
        return self._callback_store.drain_matching(
            callback_type=callback_type,
            request_id=request_id,
            group_id=group_id,
            predicate=predicate,
        )
