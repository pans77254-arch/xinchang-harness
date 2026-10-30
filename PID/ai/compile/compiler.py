"""规则转换智能体。只在用户改已确认审查点时调用。

读取修改说明后，由大模型判断改 Skill、改 workflow，或两者都改。
代码只校验：Skill 算子合法；workflow 只能使用已登记 step。
不落盘，人确认后再保存。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from ai.agents.extract_info import parse_json
from ai.agents.skill_loader import load_skill, read_skill_text
from ai.workflow.runner import guard_workflow, read_workflow_text

ALLOWED_OPS = {
    "set_diff",
    "eq",
    "seq",
    "required_fields",
    "flag_items",
    "catalog_align",
    "name_overlap",
    "frame_overflow",
    "file_prefix",
    "sheet_count",
    "survey_cert",
    "field_format",
    "notes_format",
    "catalog_files",
    "sign_conflict",
    "revision_uniform",
}
FROZEN_SKILL = ("id", "pack", "level")
PAIR_FIELDS = {
    "file_no",
    "name",
    "project_no",
    "project_name",
    "discipline",
    "stage",
    "date",
    "revision",
    "sheet_count",
    "page_count",
}
CHANGES_HINT = (Path(__file__).resolve().parents[1] / "changes" / "README.md").read_text(encoding="utf-8")


def _registered_steps() -> list[str]:
    from ai.workflow import list_steps
    from ai.workflow.runner import ensure_steps_loaded

    ensure_steps_loaded()
    return list_steps()


def _client():
    from ai.agents.extract_info import _client as build

    return build()


def guard_revision(old: dict[str, Any], new: dict[str, Any]) -> str:
    if not isinstance(new, dict):
        return "规则转换结果不是一份审查点配置"
    for key in FROZEN_SKILL:
        if old.get(key) != new.get(key):
            return f"不能改 {key}"
    checks = new.get("checks")
    if not isinstance(checks, list) or not checks:
        return "比对项不能为空"
    for check in checks:
        if not isinstance(check, dict):
            return "比对项格式不对"
        op = str(check.get("op") or "")
        if op not in ALLOWED_OPS:
            return f"这个算子还没有：{op or '空'}"
        if op != "catalog_align":
            continue
        pair_by = check.get("pair_by") or ["file_no", "name"]
        if not isinstance(pair_by, list) or not pair_by:
            return "pair_by 必须是字段列表"
        unknown = [str(item) for item in pair_by if str(item) not in PAIR_FIELDS]
        if unknown:
            return f"不能按这些字段配对：{'、'.join(unknown)}"
        identity = check.get("identity_field", "file_no")
        if identity not in (None, "") and str(identity) not in PAIR_FIELDS:
            return f"不能单独核对此字段：{identity}"
        if list(pair_by)[:1] == ["project_no"]:
            return "项目号是一套文件共用的，不能用来把目录行和文件配对"
    return ""


def _prompt(skill_text: str, workflow_text: str, text: str, steps: list[str]) -> str:
    return f"""你是规则转换智能体。根据用户自然语言，决定改 Skill、改 workflow，或两者都改。

修改说明：
{CHANGES_HINT}

判断标准：
- 只改「审什么 / 比什么 / 要不要报缺文件」→ 只改 Skill（ai/rules）。
- 改「先做什么后做什么 / 要不要 YOLO / 要不要某步转 PNG 或抽取」→ 改 workflow（ai/workflows）。
- 两者都涉及 → 都改。
- 默认优先只改 Skill。流程没变就不要动 workflow。

Skill 规则：
- 不要改 id、pack、level。
- extract 可保留；真正决定审什么的是 checks。
- 算子只能用：set_diff、eq、seq、required_fields、flag_items、catalog_align、name_overlap、frame_overflow、file_prefix、sheet_count、survey_cert、field_format、notes_format、catalog_files、sign_conflict、revision_uniform。

workflow 规则：
- 不要改 id（除非用户明确要求新建审查点）。
- nodes 里每个节点的 step 只能从已登记列表选择：{", ".join(steps)}
- 用 next / on_halt 串起来；结束写 END。
- 不能发明未登记的 step。

当前 Skill：
{skill_text}

当前 workflow：
{workflow_text}

用户要求：
{text}

只输出 JSON（不要 markdown 围栏）：
{{
  "summary": "一句话说明改了什么",
  "change_skill": true,
  "change_workflow": false,
  "unsupported": "做不到的原因；能做到则为空字符串",
  "skill_yaml": "完整 Skill YAML；不改则为空字符串",
  "workflow_yaml": "完整 workflow YAML；不改则为空字符串"
}}
"""


def revise_review_point(text: str, skill_id: str = "form.toc_index") -> dict[str, Any]:
    """返回草稿。applied 永远是 false。"""
    skill_text = read_skill_text(skill_id)
    old_skill = load_skill(skill_id)
    if skill_text is None or old_skill is None:
        return {
            "ok": False,
            "summary": "没有这个审查点",
            "skill_yaml": "",
            "workflow_yaml": "",
            "change_skill": False,
            "change_workflow": False,
            "unsupported": skill_id,
            "applied": False,
        }

    workflow_id = str(old_skill.get("workflow") or skill_id)
    workflow_text = read_workflow_text(workflow_id) or ""
    if not workflow_text:
        return {
            "ok": False,
            "summary": "没有对应工作流",
            "skill_yaml": "",
            "workflow_yaml": "",
            "change_skill": False,
            "change_workflow": False,
            "unsupported": workflow_id,
            "applied": False,
        }

    try:
        resp = _client().chat.completions.create(
            model=_model(),
            messages=[{"role": "user", "content": _prompt(skill_text, workflow_text, text.strip(), _registered_steps())}],
            temperature=0,
            max_tokens=8192,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
    except Exception as exc:
        return {
            "ok": False,
            "summary": "规则转换智能体不可达",
            "skill_yaml": "",
            "workflow_yaml": "",
            "change_skill": False,
            "change_workflow": False,
            "unsupported": str(exc),
            "applied": False,
        }

    message = resp.choices[0].message
    body = (message.content or "").strip() or str(getattr(message, "reasoning", "") or "").strip()
    try:
        data = parse_json(body)
    except (json.JSONDecodeError, ValueError) as exc:
        return {
            "ok": False,
            "summary": "规则转换结果无法解析",
            "skill_yaml": "",
            "workflow_yaml": "",
            "change_skill": False,
            "change_workflow": False,
            "unsupported": str(exc),
            "applied": False,
        }

    unsupported = str(data.get("unsupported") or "").strip()
    summary = str(data.get("summary") or "").strip() or "未说明改动"
    change_skill = bool(data.get("change_skill"))
    change_workflow = bool(data.get("change_workflow"))
    skill_draft = str(data.get("skill_yaml") or "").strip()
    workflow_draft = str(data.get("workflow_yaml") or "").strip()

    if unsupported:
        return {
            "ok": False,
            "summary": summary,
            "skill_yaml": "",
            "workflow_yaml": "",
            "change_skill": False,
            "change_workflow": False,
            "unsupported": unsupported,
            "applied": False,
        }
    if not change_skill and not change_workflow:
        return {
            "ok": False,
            "summary": summary,
            "skill_yaml": "",
            "workflow_yaml": "",
            "change_skill": False,
            "change_workflow": False,
            "unsupported": "没有给出可保存的改动",
            "applied": False,
        }

    if change_skill:
        if not skill_draft:
            return {
                "ok": False,
                "summary": summary,
                "skill_yaml": "",
                "workflow_yaml": "",
                "change_skill": False,
                "change_workflow": False,
                "unsupported": "声明改 Skill 但没有给出 YAML",
                "applied": False,
            }
        try:
            new_skill = yaml.safe_load(skill_draft)
        except yaml.YAMLError as exc:
            return {
                "ok": False,
                "summary": "Skill 不是合法 YAML",
                "skill_yaml": "",
                "workflow_yaml": "",
                "change_skill": False,
                "change_workflow": False,
                "unsupported": str(exc),
                "applied": False,
            }
        if isinstance(new_skill, dict):
            new_skill.pop("_path", None)
        reason = guard_revision(old_skill, new_skill if isinstance(new_skill, dict) else {})
        if reason:
            return {
                "ok": False,
                "summary": summary,
                "skill_yaml": "",
                "workflow_yaml": "",
                "change_skill": False,
                "change_workflow": False,
                "unsupported": reason,
                "applied": False,
            }
        skill_draft = yaml.safe_dump(new_skill, allow_unicode=True, sort_keys=False)
        if not skill_draft.endswith("\n"):
            skill_draft += "\n"
    else:
        skill_draft = ""

    if change_workflow:
        if not workflow_draft:
            return {
                "ok": False,
                "summary": summary,
                "skill_yaml": skill_draft,
                "workflow_yaml": "",
                "change_skill": change_skill,
                "change_workflow": False,
                "unsupported": "声明改 workflow 但没有给出 YAML",
                "applied": False,
            }
        try:
            new_flow = yaml.safe_load(workflow_draft)
        except yaml.YAMLError as exc:
            return {
                "ok": False,
                "summary": "workflow 不是合法 YAML",
                "skill_yaml": "",
                "workflow_yaml": "",
                "change_skill": False,
                "change_workflow": False,
                "unsupported": str(exc),
                "applied": False,
            }
        reason = guard_workflow(new_flow if isinstance(new_flow, dict) else {})
        if reason:
            return {
                "ok": False,
                "summary": summary,
                "skill_yaml": "",
                "workflow_yaml": "",
                "change_skill": False,
                "change_workflow": False,
                "unsupported": reason,
                "applied": False,
            }
        if isinstance(new_flow, dict) and new_flow.get("id") != workflow_id:
            return {
                "ok": False,
                "summary": summary,
                "skill_yaml": "",
                "workflow_yaml": "",
                "change_skill": False,
                "change_workflow": False,
                "unsupported": "不能修改工作流编号",
                "applied": False,
            }
        workflow_draft = yaml.safe_dump(new_flow, allow_unicode=True, sort_keys=False)
        if not workflow_draft.endswith("\n"):
            workflow_draft += "\n"
    else:
        workflow_draft = ""

    return {
        "ok": True,
        "summary": summary,
        "skill_yaml": skill_draft,
        "workflow_yaml": workflow_draft,
        "change_skill": change_skill,
        "change_workflow": change_workflow,
        "unsupported": "",
        "applied": False,
        "workflow_id": workflow_id,
        "skill_id": skill_id,
    }


def revise_skill(text: str, skill_id: str = "form.toc_index") -> dict[str, Any]:
    """兼容旧接口：把结果映射成 skill yaml 字段。"""
    result = revise_review_point(text, skill_id)
    return {
        "ok": result.get("ok"),
        "summary": result.get("summary"),
        "yaml": result.get("skill_yaml") or "",
        "workflow_yaml": result.get("workflow_yaml") or "",
        "change_skill": result.get("change_skill"),
        "change_workflow": result.get("change_workflow"),
        "unsupported": result.get("unsupported"),
        "applied": False,
    }


def _model() -> str:
    from ai.config import VLM_MODEL

    return VLM_MODEL
