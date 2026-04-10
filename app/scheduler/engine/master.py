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
        try:
            action_class = step_config.sub_module_data.get("action_class")
            if action_class:
                module_name, class_name = action_class.rsplit(".", 1)
                module = importlib.import_module(module_name)
                cls = getattr(module, class_name)
                return cls()

            return None

        except (ImportError, AttributeError, TypeError) as e:
            log.error(f"Error processing step {step_config.id}: {e}")
            raise RuntimeError(
                f"Failed to inject module for step {step_config.id}: {e}"
            ) from e

    def initialize(self):
        self._action_queue.clear()
        self._pipeline_steps.clear()
        self._current_action = None
        self._current_step_config = None

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

    def run(self):
        if not self._action_queue:
            log.warning("No steps to execute in the pipeline.")
            return

        for action_step in self._action_queue:
            action_instance = action_step.action_instance
            step = action_step.step_config
            if action_instance:
                self._current_action = action_instance
                self._current_step_config = step
                try:
                    action_instance.parse_params(step.sub_module_data.get("config", {}))
                except (ValidationError, TypeError, ValueError) as e:
                    log.error(f"Error parsing parameters for step {step.id}: {e}")
                    break

                log.info(
                    f"Executing step {step.id} with parameters: {step.sub_module_data.get('config', {})}"
                )
                action_instance.run()

        self._current_action = None
        self._current_step_config = None

    def get_current_status(self) -> dict[str, Any]:
        if self._current_action and self._current_step_config:
            status: dict[str, Any] = {
                "current_step_id": self._current_step_config.id,
                "current_step_name": self._current_step_config.name,
                "current_action": self._current_action.__class__.__name__,
                "all_steps": [
                    {
                        "id": step_config.step_config.id,
                        "name": step_config.step_config.name,
                        "action_class": step_config.action_instance.__class__.__name__,
                    }
                    for step_config in self._action_queue
                ],
            }
            return status

        return {}
