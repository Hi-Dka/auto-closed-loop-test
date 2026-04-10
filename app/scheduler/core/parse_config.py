import os
from dataclasses import dataclass, field
from typing import Any, Dict, List

import yaml

from app.scheduler.core.logger import base_log, TaskLoggerAdapter

log = TaskLoggerAdapter(base_log, {"tag": "ConfigParser"})


@dataclass
class StepConfig:
    id: str
    name: str
    module_config: str
    sub_module_data: Dict = field(default_factory=dict)


@dataclass
class SuiteConfig:
    name: str
    version: str
    config: Dict[str, Any]
    env: Dict[str, Any]
    pipeline: List[StepConfig]
    post_actions: List[Dict]


def _require_mapping(value: Any, field_name: str) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"'{field_name}' must be an object/dict")
    return value


def _require_list(value: Any, field_name: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"'{field_name}' must be a list")
    return value


def parse_suite_yaml(file_path: str) -> SuiteConfig:
    if not os.path.exists(file_path):
        log.error(f"Configuration file not found: {file_path}")
        raise FileNotFoundError(f"File not found: {file_path}")

    suite_dir = os.path.dirname(os.path.abspath(file_path))

    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        raise ValueError(f"Suite config is empty: {file_path}")
    if not isinstance(data, dict):
        raise ValueError(f"Suite config root must be a mapping/dict: {file_path}")

    pipeline_raw = _require_list(data.get("pipeline"), "pipeline")
    if not pipeline_raw:
        raise ValueError("'pipeline' must contain at least one step")

    steps = []
    for index, step_raw in enumerate(pipeline_raw):
        if not isinstance(step_raw, dict):
            raise ValueError(f"pipeline[{index}] must be an object/dict")

        step_id = step_raw.get("step")
        if not isinstance(step_id, str) or not step_id.strip():
            raise ValueError(f"pipeline[{index}].step is required and must be a string")

        module_config = step_raw.get("module_config")
        if not isinstance(module_config, str) or not module_config.strip():
            raise ValueError(
                f"pipeline[{index}].module_config is required and must be a string"
            )

        step_name = step_raw.get("name", step_id)
        if not isinstance(step_name, str) or not step_name.strip():
            raise ValueError(f"pipeline[{index}].name must be a non-empty string")

        step_obj = StepConfig(
            id=step_id,
            name=step_name,
            module_config=module_config,
        )

        sub_path = step_obj.module_config
        if not sub_path:
            log.error(f"Step '{step_obj.id}' missing module_config")
            raise ValueError(f"module_config is required for step '{step_obj.id}'")

        resolved_sub_path = (
            sub_path if os.path.isabs(sub_path) else os.path.join(suite_dir, sub_path)
        )

        if os.path.exists(resolved_sub_path):
            with open(resolved_sub_path, "r", encoding="utf-8") as sf:
                step_obj.sub_module_data = yaml.safe_load(sf)

            if step_obj.sub_module_data is None:
                raise ValueError(
                    f"module_config for step '{step_obj.id}' is empty: {resolved_sub_path}"
                )
            if not isinstance(step_obj.sub_module_data, dict):
                raise ValueError(
                    f"module_config for step '{step_obj.id}' must be an object/dict: {resolved_sub_path}"
                )

            action_class = step_obj.sub_module_data.get("action_class")
            if not isinstance(action_class, str) or not action_class.strip():
                raise ValueError(
                    f"module_config for step '{step_obj.id}' must define non-empty 'action_class'"
                )

            step_obj.sub_module_data["config"] = _require_mapping(
                step_obj.sub_module_data.get("config"),
                f"module_config.config (step '{step_obj.id}')",
            )
        else:
            log.error(
                f"Step '{step_obj.id}' module_config not found: {sub_path} (resolved: {resolved_sub_path})"
            )
            raise FileNotFoundError(
                f"module_config not found for step '{step_obj.id}': {resolved_sub_path}"
            )

        steps.append(step_obj)

    return SuiteConfig(
        name=data.get("name", "Unknown Suite"),
        version=data.get("version", "1.0.0"),
        config=_require_mapping(data.get("config"), "config"),
        env=_require_mapping(data.get("env"), "env"),
        pipeline=steps,
        post_actions=_require_list(data.get("post_actions"), "post_actions"),
    )
