from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Literal, Optional, TypeVar

from app.scheduler.core.base_action import BaseAction, BaseParam, CompletionPolicy
from app.scheduler.core.logger import base_log, TaskLoggerAdapter


log = TaskLoggerAdapter(base_log, {"tag": "TemplateAction"})

TimeoutBehavior = Literal["fail_fast", "partial_ok", "continue_on_timeout"]
TParam = TypeVar("TParam", bound=BaseParam)


@dataclass(frozen=True)
class ActionPhase:
    name: str
    send_count: int
    completion_policy: CompletionPolicy
    timeout: Optional[float] = None
    timeout_behavior: TimeoutBehavior = "fail_fast"
    min_callbacks_on_timeout: int = 0
    request_id_validation_enabled: bool = False
    need_callback: bool = True


class TemplateAction(BaseAction[TParam]):
    """Reusable phase-driven action template for multi-send / multi-receive workflows."""

    def run(self) -> bool:
        log.info(f"Running {self.__class__.__name__} with params: {self._params}")

        for phase in self.build_phases():
            if not self._execute_phase(phase):
                return False

        log.info(f"{self.__class__.__name__} completed.")
        return True

    @abstractmethod
    def build_phases(self) -> list[ActionPhase]:
        """Return the ordered phase list for this action."""

    @abstractmethod
    def dispatch_request(
        self, request_id: str, group_id: str, phase: ActionPhase
    ) -> bool:
        """Send a single request for the given phase."""

    @abstractmethod
    def _build_request_id(self) -> str:
        """Build a unique request identifier for one outbound message."""

    @abstractmethod
    def _build_group_id(self) -> str:
        """Build a unique group identifier for one phase execution."""

    def _execute_phase(self, phase: ActionPhase) -> bool:
        phase_timeout = self._resolve_phase_timeout(phase)
        log.info(
            f"Executing phase '{phase.name}' with send_count={phase.send_count}, policy={phase.completion_policy.count.kind}, timeout={phase_timeout}"
        )

        if phase.send_count <= 0:
            log.error("send_count must be greater than 0")
            return False

        group_id = self._build_group_id()
        request_ids: list[str] = []

        for _ in range(phase.send_count):
            request_id = self._build_request_id()
            if not self.dispatch_request(
                request_id=request_id, group_id=group_id, phase=phase
            ):
                return False
            request_ids.append(request_id)

        final_policy = phase.completion_policy

        if phase.request_id_validation_enabled:
            final_policy = phase.completion_policy.with_request_ids(request_ids)

        if not phase.need_callback:
            log.info(f"Phase '{phase.name}' does not require callbacks, skipping wait.")
            return True

        try:
            callbacks = self._wait_for_callbacks_by_policy(
                policy=final_policy,
                timeout=phase_timeout,
                callback_type=self.callback_type,
                group_id=group_id,
            )
        except TimeoutError:
            return self._handle_phase_timeout(phase=phase, group_id=group_id)

        if not self._validate_phase_callbacks(phase=phase, callbacks=callbacks):
            log.error(f"Phase '{phase.name}' callback validation failed.")
            return False

        log.info(f"Phase '{phase.name}' completed with {len(callbacks)} callback(s).")
        return True

    def _handle_phase_timeout(self, phase: ActionPhase, group_id: str) -> bool:
        if phase.timeout_behavior == "continue_on_timeout":
            log.warning(
                f"Phase '{phase.name}' timed out, but continuing by timeout behavior."
            )
            return True

        if phase.timeout_behavior == "partial_ok":
            partial_callbacks = self._drain_matching_callbacks(
                callback_type=self.callback_type,
                group_id=group_id,
            )
            if len(partial_callbacks) >= phase.min_callbacks_on_timeout:
                log.warning(
                    f"Phase '{phase.name}' timed out; accepted partial callbacks {len(partial_callbacks)} (min required {phase.min_callbacks_on_timeout})."
                )
                return True

            log.error(
                f"Phase '{phase.name}' timed out; partial callbacks {len(partial_callbacks)} below min required {phase.min_callbacks_on_timeout}."
            )
            return False

        log.error(f"Phase '{phase.name}' timed out with fail_fast behavior.")
        return False

    def _resolve_phase_timeout(self, phase: ActionPhase) -> float:
        timeout = phase.timeout if phase.timeout is not None else self.phase_timeout_seconds
        if timeout <= 0:
            raise ValueError(
                f"Phase '{phase.name}' timeout must be greater than 0, got: {timeout}"
            )
        return float(timeout)

    @abstractmethod
    def _validate_phase_callbacks(
        self, phase: ActionPhase, callbacks: list[dict[str, Any]]
    ) -> bool: ...


    @property
    @abstractmethod
    def callback_type(self) -> str:
        """The callback_type this action listens for."""

    @property
    @abstractmethod
    def phase_timeout_seconds(self) -> float:
        """Return the timeout used for each phase."""
