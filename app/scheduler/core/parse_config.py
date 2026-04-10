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


def parse_suite_yaml(file_path: str) -> SuiteConfig:
    if not os.path.exists(file_path):
        log.error(f"Configuration file not found: {file_path}")
        raise FileNotFoundError(f"File not found: {file_path}")

    suite_dir = os.path.dirname(os.path.abspath(file_path))

    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    steps = []
    for step_raw in data.get("pipeline", []):
        step_obj = StepConfig(
            id=step_raw.get("step"),
            name=step_raw.get("name", step_raw.get("step")),
            module_config=step_raw.get("module_config"),
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
        config=data.get("config", {}),
        env=data.get("env", {}),
        pipeline=steps,
        post_actions=data.get("post_actions", []),
    )
