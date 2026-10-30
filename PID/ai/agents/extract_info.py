"""信息抽取智能体。字段由 Skill 给出，模型只负责抽取，不负责比对。"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

from ai.config import VLM_API_KEY, VLM_BASE_URL, VLM_EXTRA_BODY, VLM_MODEL, VLM_TIMEOUT
from ai.prompts import render


def _client():
    from openai import OpenAI

    return OpenAI(base_url=VLM_BASE_URL, api_key=VLM_API_KEY, timeout=VLM_TIMEOUT)


def _shrink(image_path: Path, max_side: int = 2048) -> Path:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    image = Image.open(image_path).convert("RGB")
    if max(image.size) <= max_side:
        return image_path
    image.thumbnail((max_side, max_side))
    out = image_path.with_name(image_path.stem + "-vlm.png")
    image.save(out)
    return out


def parse_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("抽取结果不是 JSON 对象")
    return data


def _field_lines(fields: list[dict[str, Any]]) -> str:
    lines = []
    for field in fields:
        name = field.get("name") or ""
        desc = field.get("desc") or ""
        lines.append(f"- {name}：{desc}")
    return "\n".join(lines)


def extract_json(
    *,
    prompt_id: str,
    fields: list[dict[str, Any]],
    text: str = "",
    image_path: str | None = None,
    expect: str = "object",
    max_side: int = 2048,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """text 与 image_path 至少给一个。提示词从库中按 prompt_id 加载。

    max_side：图片送模型前的最长边上限，小字密集的裁图（说明栏）可调大。
    """
    shape_id = "extract.catalog_shape" if expect == "catalog" else "extract.object_shape"
    prompt = render(
        "extract.user",
        task=render(prompt_id),
        shape=render(shape_id),
        fields=_field_lines(fields),
    )
    if text:
        prompt += render("extract.text_suffix", text=text[:40000])

    content: Any
    if image_path:
        path = _shrink(Path(image_path), max_side=max_side)
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
        ]
    else:
        content = prompt

    try:
        resp = _client().chat.completions.create(
            model=VLM_MODEL,
            messages=[{"role": "user", "content": content}],
            temperature=0,
            max_tokens=max_tokens,
            extra_body=VLM_EXTRA_BODY,
        )
    except Exception as exc:
        return {"_error": f"大模型不可达：{exc}"}

    message = resp.choices[0].message
    body = (message.content or "").strip()
    if not body:
        body = str(getattr(message, "reasoning", "") or "").strip()
    try:
        return parse_json(body)
    except Exception as exc:
        return {"_error": f"抽取结果无法解析：{exc}", "_raw": body[:1000]}


def judge_json(*, prompt_id: str, max_tokens: int = 4096, **values: object) -> dict[str, Any]:
    """纯文本判定调用：按 prompt_id 渲染提示词（变量用 {{name}} 注入），要求模型只回 JSON。

    供 llm_judge 算子使用。与 extract_json 共用客户端与解析逻辑，模型访问不散落到算子里。
    """
    prompt = render(prompt_id, **values)
    try:
        resp = _client().chat.completions.create(
            model=VLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=max_tokens,
            extra_body=VLM_EXTRA_BODY,
        )
    except Exception as exc:
        return {"_error": f"大模型不可达：{exc}"}
    message = resp.choices[0].message
    body = (message.content or "").strip()
    if not body:
        body = str(getattr(message, "reasoning", "") or "").strip()
    try:
        return parse_json(body)
    except Exception as exc:
        return {"_error": f"判定结果无法解析：{exc}", "_raw": body[:1000]}
