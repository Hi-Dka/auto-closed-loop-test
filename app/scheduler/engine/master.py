import importlib
from typing import Optional, Any
from dataclasses import dataclass

from pydantic import ValidationError

from app.scheduler.core.base_action import BaseAction
from app.scheduler.core.logger import base_log, TaskLoggerAdapter
from app.scheduler.core.meta import SingletonMeta
from app.scheduler.core.parse_config import StepConfig, SuiteConfig, parse_suite_yaml


log = TaskLoggerAdapter(base_log, {"tag": "MasterScheduler"})


@dataclass
class ActionStep:
    action_instance: BaseAction
    step_config: StepConfig


class MasterScheduler(metaclass=SingletonMeta):
    def __init__(self, config_path: str):
        self._config_path = config_path
        self._suite_config: Optional[SuiteConfig] = None
        self._current_action: Optional[BaseAction] = None
        self._current_step_config: Optional[StepConfig] = None
        self._action_queue: list[ActionStep] = []
        self._pipeline_steps = []
        self._run_status: str = "idle"
        self._last_error: Optional[str] = None
        self._last_failed_step_id: Optional[str] = None
        self._last_failed_step_name: Optional[str] = None

    def dispatch_callback(self, data: dict, callback_type: str):
        log.info(f"Dispatching callback of type '{callback_type}' with data: {data}")
        self._dispatch_callback(data, callback_type)

    def _dispatch_callback(self, data: dict, callback_type: str):
        if not self._current_action:
            log.warning(
                f"Received callback (type: {callback_type}) but no action is running"
            )
            return

        # Validate callback type if specified
        if callback_type:
            expected_type = (
                self._current_step_config.sub_module_data.get("callback_type", None)
                if self._current_step_config
                else None
            )
            if expected_type and callback_type != expected_type:
                log.warning(
                    f"Callback type '{callback_type}' does not match expected type {expected_type} for step {self._current_step_config.id if self._current_step_config else 'unknown'}"
                )
                return

        self._current_action.notify_callback(data, callback_type=callback_type)

    def _inject_modules(self, step_config: StepConfig) -> BaseAction | None:
        action_class = step_config.sub_module_data.get("action_class")

        if not isinstance(action_class, str) or not action_class.strip():
            raise RuntimeError(
                f"Failed to inject module for step {step_config.id}: missing or invalid action_class"
            )

        try:
            module_name, class_name = action_class.rsplit(".", 1)
        except ValueError as e:
            raise RuntimeError(
                f"Failed to inject module for step {step_config.id}: invalid action_class format '{action_class}', expected '<module>.<ClassName>'"
            ) from e

        try:
            module = importlib.import_module(module_name)
        except ImportError as e:
            log.error(f"Error importing module for step {step_config.id}: {e}")
            raise RuntimeError(
                f"Failed to inject module for step {step_config.id}: cannot import module '{module_name}'"
            ) from e

        try:
            cls = getattr(module, class_name)
        except AttributeError as e:
            log.error(f"Error resolving class for step {step_config.id}: {e}")
            raise RuntimeError(
                f"Failed to inject module for step {step_config.id}: class '{class_name}' not found in module '{module_name}'"
            ) from e

        if not isinstance(cls, type):
            raise RuntimeError(
                f"Failed to inject module for step {step_config.id}: '{action_class}' is not a class"
            )

        if not issubclass(cls, BaseAction):
            raise RuntimeError(
                f"Failed to inject module for step {step_config.id}: '{action_class}' must subclass BaseAction"
            )

        try:
            return cls()  # pyright: ignore[reportCallIssue]
        except TypeError as e:
            log.error(f"Error instantiating class for step {step_config.id}: {e}")
            raise RuntimeError(
                f"Failed to inject module for step {step_config.id}: unable to instantiate '{action_class}'"
            ) from e

    def initialize(self):
        self._action_queue.clear()
        self._pipeline_steps.clear()
        self._current_action = None
        self._current_step_config = None
        self._run_status = "initialized"
        self._last_error = None
        self._last_failed_step_id = None
        self._last_failed_step_name = None

        try:
            self._suite_config = parse_suite_yaml(self._config_path)
            log.info(
                f"Loaded suite: {self._suite_config.name} v{self._suite_config.version}"
            )
        except (FileNotFoundError, ValueError, OSError) as e:
            log.error(f"Error loading suite configuration: {e}")
            raise RuntimeError(f"Failed to load suite configuration: {e}") from e

        for step in self._suite_config.pipeline:
            log.info(f"Processing step: {step.id} - {step.name}")
            action_instance = self._inject_modules(step)
            if action_instance:
                self._action_queue.append(ActionStep(action_instance, step))

    def run(self) -> bool:
        if not self._action_queue:
            log.warning("No steps to execute in the pipeline.")
            self._run_status = "failed"
            self._last_error = "No steps to execute in the pipeline"
            return False

        self._run_status = "running"
        self._last_error = None
        self._last_failed_step_id = None
        self._last_failed_step_name = None

        try:
            for action_step in self._action_queue:
                action_instance = action_step.action_instance
                step = action_step.step_config
                if action_instance:
                    self._current_action = action_instance
                    self._current_step_config = step
                    try:
                        action_instance.parse_params(
                            step.sub_module_data.get("config", {})
                        )
                    except (ValidationError, TypeError, ValueError) as e:
                        log.error(f"Error parsing parameters for step {step.id}: {e}")
                        self._run_status = "failed"
                        self._last_error = (
                            f"Parameter parsing failed for step {step.id}: {e}"
                        )
                        self._last_failed_step_id = step.id
                        self._last_failed_step_name = step.name
                        return False

                    log.info(
                        f"Executing step {step.id} with parameters: {step.sub_module_data.get('config', {})}"
                    )
                    step_result = action_instance.run()
                    if not step_result:
                        self._run_status = "failed"
                        self._last_error = f"Step {step.id} returned failure"
                        self._last_failed_step_id = step.id
                        self._last_failed_step_name = step.name
                        return False

            self._run_status = "success"
            return True
        finally:
            self._current_action = None
            self._current_step_config = None

    def get_current_status(self) -> dict[str, Any]:
        status: dict[str, Any] = {
            "run_status": self._run_status,
            "last_error": self._last_error,
            "failed_step_id": self._last_failed_step_id,
            "failed_step_name": self._last_failed_step_name,
            "all_steps": [
                {
                    "id": step_config.step_config.id,
                    "name": step_config.step_config.name,
                    "action_class": step_config.action_instance.__class__.__name__,
                }
                for step_config in self._action_queue
            ],
        }

        if self._current_action and self._current_step_config:
            status["current_step_id"] = self._current_step_config.id
            status["current_step_name"] = self._current_step_config.name
            status["current_action"] = self._current_action.__class__.__name__

        return status
