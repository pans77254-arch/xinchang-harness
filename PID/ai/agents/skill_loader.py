"""审查点 Skill 加载器。YAML 即规则，禁止在本文件写具体审查逻辑。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

RULES_DIR = Path(__file__).resolve().parents[1] / "rules"


def list_skills(*, include_disabled: bool = True) -> list[dict[str, Any]]:
    out = []
    if not RULES_DIR.exists():
        return out
    for p in sorted(RULES_DIR.glob("*.yaml")):
        if p.name.startswith("_"):
            continue
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        # 没有 id 的不是审查点（如白名单等配套资源），不当 Skill 加载。
        if not isinstance(data, dict) or not data.get("id"):
            continue
        data["_path"] = str(p)
        if not include_disabled and not data.get("enabled", True):
            continue
        out.append(data)
    return out


def load_skill(skill_id: str) -> dict[str, Any] | None:
    for s in list_skills():
        if s.get("id") == skill_id:
            return s
    return None


def skill_path(skill_id: str) -> Path | None:
    skill = load_skill(skill_id)
    if not skill:
        return None
    path = Path(skill.get("_path") or "")
    if path.parent.resolve() != RULES_DIR.resolve() or not path.is_file():
        return None
    return path


def read_skill_text(skill_id: str) -> str | None:
    path = skill_path(skill_id)
    if path is None:
        return None
    return path.read_text(encoding="utf-8")


def save_skill_text(skill_id: str, text: str) -> None:
    path = skill_path(skill_id)
    if path is None:
        raise FileNotFoundError(skill_id)
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"规则格式不对：{exc}") from exc
    if not isinstance(data, dict) or not data.get("id"):
        raise ValueError("规则必须包含审查点编号")
    if data.get("id") != skill_id:
        raise ValueError("不能修改审查点编号")
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def load_resource(name: str) -> Any:
    """读取规则目录下的配套资源（如错别字白名单 notes_glossary.yaml）。

    只允许读 ai/rules 内的文件，防止 YAML 里写任意路径。文件不存在或格式错返回 None。
    """
    if not name or not str(name).strip():
        return None
    path = (RULES_DIR / str(name)).resolve()
    if path.parent != RULES_DIR.resolve() or not path.is_file():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None


def union_needs(skill_ids: list[str] | None) -> list[str]:
    skills = list_skills(include_disabled=False)
    if skill_ids:
        skills = [s for s in skills if s.get("id") in skill_ids]
    needs: list[str] = []
    for s in skills:
        for n in s.get("needs") or []:
            if n not in needs:
                needs.append(n)
    return needs
