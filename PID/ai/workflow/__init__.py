"""工作流步骤注册。workflow.yaml 只能引用这里登记过的 step。"""

from __future__ import annotations

from typing import Any, Callable

StepFn = Callable[[dict[str, Any]], dict[str, Any]]

STEPS: dict[str, StepFn] = {}


def step(name: str):
    def deco(fn: StepFn) -> StepFn:
        STEPS[name] = fn
        return fn

    return deco


def get_step(name: str) -> StepFn:
    if name not in STEPS:
        raise KeyError(f"未登记的工作流步骤：{name}")
    return STEPS[name]


def list_steps() -> list[str]:
    return sorted(STEPS)
