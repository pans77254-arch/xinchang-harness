"""规划路由。只从已经登记并启用的检查点里选工具和技能，不新增规则。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# 检测之后才能做的检查。未写 when 的审查点不进入本次 PID 计划。
_WHEN = {"has_notes", "has_frame", "has_chart"}


def build_plan(pages: list[dict[str, Any]]) -> dict[str, Any]:
    """根据已抽出的页，生成本次要调用的工具和技能。"""
    from ai.agents.skill_loader import list_skills

    tools: list[str] = ["pid.detect"] if pages else []
    skills: list[dict[str, str]] = []
    if tools:
        for skill in list_skills(include_disabled=False):
            when = str(skill.get("when") or "")
            skill_id = str(skill.get("id") or "")
            if when not in _WHEN or not skill_id:
                continue
            skills.append({"id": skill_id, "name": str(skill.get("name") or skill_id), "when": when})
    return {
        "tools": tools,
        "skills": skills,
        "page_count": len(pages),
        "reason": "" if pages else "没有已抽出的页图，不安排检测和检查",
    }


def load_extracted_pages(folder: str) -> list[dict[str, Any]]:
    """读取上传阶段已经写好的 info JSON，不再重新转图。"""
    pages: list[dict[str, Any]] = []
    root = Path(folder)
    if not root.is_dir():
        return pages
    for info in sorted(root.glob("*.info.json")):
        try:
            data = json.loads(info.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        file_name = str(data.get("file") or info.stem)
        for record in data.get("pages") or []:
            if not isinstance(record, dict):
                continue
            image = str(record.get("metadata_png") or "")
            if not image:
                continue
            pages.append(
                {
                    "file": file_name,
                    "page": record.get("page") or 0,
                    "image": image,
                    "info": str(info),
                    "error": "",
                }
            )
    return pages


def notes_from_info(info_paths: list[str]) -> dict[str, Any]:
    """把检测智能体写回的说明 info 收成错别字检查能读的工件。不再次抄写。"""
    from ai.tools.extract_drawing_json import read_info
    from ai.tools.extract_notes import discipline_of, drawing_no_of

    files: list[dict[str, Any]] = []
    for raw in info_paths:
        if not Path(raw).is_file():
            continue
        book = read_info(raw)
        items = []
        for page in book.get("pages") or []:
            lines = (page.get("notes") or {}).get("lines") or []
            if lines:
                items.append({"page": page.get("page"), "lines": lines, "bbox": None, "source": "info"})
        if not items:
            continue
        file_name = str(book.get("file") or "")
        drawing_no = str((book.get("fields") or {}).get("文件号") or "") or drawing_no_of(file_name)
        files.append(
            {
                "file": file_name,
                "drawing_no": drawing_no,
                "discipline": discipline_of(file_name, drawing_no),
                "items": items,
                "errors": [],
            }
        )
    return {"files": files, "logs": []}


_WHEN_SOURCE = {"has_notes": "notes", "has_frame": "frame", "has_chart": "chart"}


def save_checkpoint(name: str, when: str, criterion: str) -> dict[str, Any]:
    """把一条已解析的检查要求写成新的审查点。编号按规则内容生成，重复描述不另建。"""
    import hashlib

    import yaml

    from ai.agents.skill_loader import RULES_DIR

    title = " ".join(str(name or "").split())
    rule = " ".join(str(criterion or "").split())
    if when not in _WHEN_SOURCE:
        return _need_human(rule, "只能检查说明、图框或图表中已抽出的内容", name=title, when=when, criterion=rule)
    if not title or not rule:
        return _need_human(rule, "缺少检查名称或判定规则", name=title, when=when, criterion=rule)
    skill_id = "pid.nl_" + hashlib.sha1(f"{when}\n{rule}".encode("utf-8")).hexdigest()[:8]
    path = RULES_DIR / f"{skill_id}.yaml"
    payload = {
        "id": skill_id,
        "name": title,
        "pack": "pid",
        "level": "drawing",
        "enabled": True,
        "when": when,
        "severity": "low",
        "basis": rule,
        "needs": [_WHEN_SOURCE[when]],
        "checks": [
            {
                "op": "llm_judge",
                "prompt": "judge.dynamic",
                "criterion": rule,
                "min_confidence": 0.7,
                "type": "dynamic_check",
                "msg": "{drawing_no} {name}：「{wrong}」应为「{correct}」（{reason}）",
            }
        ],
    }
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"ok": True, "id": skill_id, "name": title, "when": when, "path": str(path), "applied": True}


def _need_human(text: str, unsupported: str, *, name: str = "", when: str = "", criterion: str = "") -> dict[str, Any]:
    """返回待人工补充的草稿，不写文件。"""
    chosen = when if when in _WHEN_SOURCE else ""
    title = " ".join(str(name or "").split())
    rule = " ".join(str(criterion or "").split())
    ready = bool(title and chosen and rule) and not str(unsupported or "").strip()
    return {
        "ok": False,
        "need_human": True,
        "ready": ready,
        "applied": False,
        "unsupported": "" if ready else unsupported,
        "text": text,
        "draft": {"name": title, "when": chosen, "criterion": rule or text},
    }


def finish_checkpoint(text: str, data: dict[str, Any] | None) -> dict[str, Any]:
    """信息完整就直接生成检查点。缺内容或超出范围时才交给人工补充。"""
    if not isinstance(data, dict):
        return _need_human(text, "草稿无法解析，请人工填写")
    name = str(data.get("name") or "")
    when = str(data.get("when") or "")
    criterion = str(data.get("criterion") or "")
    unsupported = str(data.get("unsupported") or "").strip()
    if unsupported or when not in _WHEN_SOURCE or not name.strip() or not criterion.strip():
        return _need_human(
            text,
            unsupported or "自动结果不完整，请人工补全检查名称、检查对象和判定规则",
            name=name,
            when=when,
            criterion=criterion,
        )
    return save_checkpoint(name, when, criterion)


def create_checkpoint(text: str) -> dict[str, Any]:
    """用自然语言生成检查点。只有整理不出来时才返回草稿，等人补充。"""
    from ai.agents.extract_info import _client, parse_json
    from ai.config import VLM_EXTRA_BODY, VLM_MODEL

    description = " ".join(str(text or "").split())
    if not description:
        return _need_human("", "请写出要增加的检查点")
    prompt = (
        "把下面的审查要求整理成一个检查点。只能检查已经抽取的三类内容之一。\n"
        "when 只能是 has_notes（说明文字）、has_frame（图框栏位）、has_chart（图表单元格）。\n"
        "如果要求依赖还没抽取的内容，例如线型、拓扑、量距，unsupported 写原因，其余字段留空。\n"
        "只输出 JSON：{\"name\":\"短名称\",\"when\":\"has_notes\",\"criterion\":\"可执行的判定规则\",\"unsupported\":\"\"}\n\n"
        f"要求：{description}"
    )
    try:
        resp = _client().chat.completions.create(
            model=VLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=800,
            extra_body=VLM_EXTRA_BODY,
        )
        body = (resp.choices[0].message.content or "").strip()
        data = parse_json(body)
    except Exception as exc:
        return _need_human(description, f"检查点生成失败：{exc}")
    return finish_checkpoint(description, data if isinstance(data, dict) else None)
