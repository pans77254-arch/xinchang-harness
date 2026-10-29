"""
能力转化判断规则引擎（专利核心发明点实现）
面向异构智能体的能力转化方法：能力 -> 智能体 / 插件 / 工作流 / 技能
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class CapabilityForm(Enum):
    """能力转化后的目标形态"""
    AGENT = "agent"          # 智能体：需模型自主调度 + 多工具编排
    PLUGIN = "plugin"        # 插件：依赖外部工具 / 沙箱 / 凭证
    WORKFLOW = "workflow"    # 工作流：多步骤且有固定先后顺序
    SKILL = "skill"          # 技能：单一功能、可独立调用、无状态


@dataclass
class Capability:
    """能力描述（S1 输入）"""
    name: str
    description: str = ""
    # S2 能力分析维度
    needs_autonomous_dispatch: bool = False  # 是否需模型自主调度
    needs_external_credential: bool = False  # 是否依赖外部凭证 / 沙箱
    multi_step: bool = False                 # 是否多步骤
    has_fixed_order: bool = False            # 是否有固定先后顺序


# S2 能力分析：从能力元数据提取判断维度
def analyze_capability(raw: dict[str, Any]) -> Capability:
    return Capability(
        name=raw["name"],
        description=raw.get("description", ""),
        needs_autonomous_dispatch=raw.get("needs_autonomous_dispatch", False),
        needs_external_credential=raw.get("needs_external_credential", False),
        multi_step=raw.get("multi_step", False),
        has_fixed_order=raw.get("has_fixed_order", False),
    )


# S3 转化判断（核心发明点）：优先级匹配规则引擎
def convert(cap: Capability) -> CapabilityForm:
    # 规则 1：需模型自主调度 -> 智能体
    if cap.needs_autonomous_dispatch:
        return CapabilityForm.AGENT
    # 规则 2：依赖外部凭证 / 沙箱 -> 插件
    if cap.needs_external_credential:
        return CapabilityForm.PLUGIN
    # 规则 3：多步骤且有固定顺序 -> 工作流
    if cap.multi_step and cap.has_fixed_order:
        return CapabilityForm.WORKFLOW
    # 规则 4：其余 -> 技能
    return CapabilityForm.SKILL


# S4 转化执行：生成模板 + 注册到平台对应模块
def generate_manifest(cap: Capability, form: CapabilityForm) -> dict[str, Any]:
    """根据形态生成对应模板（manifest）"""
    if form == CapabilityForm.SKILL:
        return {"type": "skill", "name": cap.name, "single_shot": True}
    if form == CapabilityForm.WORKFLOW:
        return {"type": "workflow", "name": cap.name, "steps": [], "order": "fixed"}
    if form == CapabilityForm.PLUGIN:
        return {"type": "plugin", "name": cap.name, "credential": "required"}
    if form == CapabilityForm.AGENT:
        return {"type": "agent", "name": cap.name, "scheduler": "model"}
    return {}


REGISTRY = {
    CapabilityForm.AGENT: "AgentCenter",
    CapabilityForm.PLUGIN: "PluginMarket",
    CapabilityForm.WORKFLOW: "WorkflowEngine",
    CapabilityForm.SKILL: "SkillMarket",
}


def register(cap: Capability, form: CapabilityForm) -> dict[str, Any]:
    return {
        "name": cap.name,
        "form": form.value,
        "target": REGISTRY[form],
        "manifest": generate_manifest(cap, form),
    }


# 完整转化流程（S1 -> S2 -> S3 -> S4）
def convert_capability(raw: dict[str, Any]) -> dict[str, Any]:
    cap = analyze_capability(raw)      # S2 能力分析
    form = convert(cap)                # S3 转化判断（核心）
    return register(cap, form)         # S4 转化执行


if __name__ == "__main__":
    # 实例：涉密审查能力的五个子能力
    examples = [
        {"name": "密级标注检查"},
        {"name": "涉密内容检测"},
        {"name": "脱敏建议", "needs_external_credential": True},
        {"name": "涉密审查完整流程", "multi_step": True, "has_fixed_order": True},
        {"name": "自主涉密审查", "needs_autonomous_dispatch": True},
    ]
    for ex in examples:
        result = convert_capability(ex)
        print(f"{ex['name']:　<10} -> {result['form']:　<8} -> {result['target']}")
