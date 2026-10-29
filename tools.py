"""政企工具实现 + 注册表（seam 落地：运行时只认 TOOL_REGISTRY 映射）"""

from __future__ import annotations

import glob
import os
import re
from pathlib import Path
from typing import Any, Callable

# 项目根目录（本文件所在目录）
ROOT_DIR = Path(__file__).resolve().parent
DOC_DIR = ROOT_DIR / "docs"

SENSITIVE_WORDS = [
    # 密级
    "绝密", "机密", "秘密", "涉密", "内部资料", "严禁外传",
    # 信创涉密域
    "军工", "国安", "国密", "密码", "加密", "核",
]


def _resolve_doc_path(path: str) -> Path | None:
    """将路径解析到 docs/ 内；拒绝目录穿越。"""
    raw = Path(path)
    if raw.is_absolute():
        candidate = raw.resolve()
    else:
        candidate = (ROOT_DIR / raw).resolve()
    doc_root = DOC_DIR.resolve()
    try:
        candidate.relative_to(doc_root)
    except ValueError:
        return None
    return candidate


def search_docs(keyword: str) -> list[dict[str, str]] | str:
    """在内网文档库中按关键词检索（文件名+路径+正文联合匹配）。"""
    normalized = re.sub(r"\s+", " ", keyword.strip())
    if not normalized:
        return "请提供非空检索关键词"

    terms = [t for t in normalized.split(" ") if t]
    compact_query = "".join(terms)
    results: list[tuple[int, dict[str, str | int]]] = []
    pattern = str(DOC_DIR / "**" / "*.md")
    for path in glob.glob(pattern, recursive=True):
        with open(path, encoding="utf-8") as f:
            content = f.read()

        rel = os.path.relpath(path, ROOT_DIR).replace("\\", "/")
        filename = os.path.basename(path)
        searchable = f"{filename}\n{rel}\n{content}"
        compact_searchable = re.sub(r"\s+", "", searchable)
        score = 0
        if normalized in searchable:
            score = 100
        elif compact_query and compact_query in compact_searchable:
            score = 80
        else:
            hit_terms = [t for t in terms if t in searchable or t in compact_searchable]
            if hit_terms:
                score = len(hit_terms) * 10

        if score > 0:
            results.append(
                (
                    score,
                    {
                        "title": filename,
                        "path": rel,
                        "score": score,
                    },
                )
            )

    if not results:
        return f"未找到包含「{keyword}」的文档"

    results.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in results]


def read_file(path: str) -> str:
    """读取 docs/ 目录内的文档内容。"""
    resolved = _resolve_doc_path(path)
    if resolved is None:
        return f"拒绝访问：路径必须在 docs/ 目录内（收到：{path}）"
    if not resolved.is_file():
        return f"文件不存在：{path}"
    return resolved.read_text(encoding="utf-8")


def check_classification(text: str) -> dict[str, str] | str:
    """密级标注检查：识别标注密级，判断与内容涉密程度是否匹配。"""
    if not text.strip():
        return "请提供待检查文本"
    levels = ["绝密", "机密", "秘密", "内部资料", "公开"]
    marked = [l for l in levels if l in text]
    if not marked:
        return {"标注密级": "未标注", "结论": "❌ 缺少密级标注，涉密文件必须标注密级"}
    high = any(w in text for w in ["绝密", "军工", "国密", "核"])
    if high and marked[0] in ("秘密", "内部资料"):
        return {"标注密级": marked[0], "结论": "⚠️ 内容含高涉密信息，密级可能偏低，建议升级"}
    return {"标注密级": marked[0], "结论": "✅ 密级标注与内容匹配"}


def check_sensitive(text: str) -> dict[str, list[str]] | str:
    """涉密内容检查（信创涉密域词表）。"""
    if not text.strip():
        return "请提供待检查文本"
    hits = [w for w in SENSITIVE_WORDS if w in text]
    return {"命中涉密内容": hits} if hits else "未发现涉密内容"


def suggest_desensitization(text: str) -> list[str] | str:
    """脱敏建议：手机号、人名/职务、具体数据。"""
    if not text.strip():
        return "请提供待检查文本"
    suggestions = []
    if re.search(r"1[3-9]\d{9}", text):
        suggestions.append("手机号 → 用「1XX」替代")
    if re.search(r"[\u4e00-\u9fa5]{1,4}(?:处长|主任|局长|经理|总)", text):
        suggestions.append("人名/职务 → 用「某某」替代")
    if re.search(r"\d+(?:%|万|亿|元|路)", text):
        suggestions.append("具体数据 → 用「XX」替代")
    return suggestions if suggestions else "未发现需脱敏的信息"


# 注册表：新增工具时在此登记实现函数
TOOL_REGISTRY: dict[str, Callable[..., Any]] = {
    "search_docs": search_docs,
    "read_file": read_file,
    "check_classification": check_classification,
    "check_sensitive": check_sensitive,
    "suggest_desensitization": suggest_desensitization,
}
