"""从提示词库加载模板。本文件不写提示词正文。"""

from __future__ import annotations

from pathlib import Path

import yaml

PROMPTS_DIR = Path(__file__).resolve().parent
_CACHE: dict[str, str] | None = None


def _read_file(path: Path) -> dict[str, str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    found: dict[str, str] = {}
    if isinstance(data, dict) and isinstance(data.get("text"), str) and data.get("id"):
        found[str(data["id"])] = data["text"]
        return found
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str):
                found[str(key)] = value
            elif isinstance(value, dict) and isinstance(value.get("text"), str):
                found[str(key)] = value["text"]
    return found


def load_all() -> dict[str, str]:
    global _CACHE
    if _CACHE is None:
        loaded: dict[str, str] = {}
        for path in sorted(PROMPTS_DIR.glob("*.yaml")):
            loaded.update(_read_file(path))
        _CACHE = loaded
    return _CACHE


def load_prompt(prompt_id: str) -> str:
    prompts = load_all()
    if prompt_id not in prompts:
        known = "、".join(sorted(prompts)) or "空"
        raise KeyError(f"提示词库没有 {prompt_id}。现有：{known}")
    return prompts[prompt_id]


def render(prompt_id: str, **values: object) -> str:
    text = load_prompt(prompt_id)
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", "" if value is None else str(value))
    return text.strip()
