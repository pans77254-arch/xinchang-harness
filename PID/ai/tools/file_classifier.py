"""文件夹文件分类：识别目录、PID工艺流程图、平面图（CAD图纸）。

流程：文件名别名优先 → 未命中则转 PNG 送 VLM 判定。
目录识别逻辑提炼自 steps_toc.detect_catalog，目录索引一致性通过 find_catalog 复用。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ai.agents.extract_info import extract_json
from ai.config import PDF_DPI, WORK_ROOT
from ai.tools.pdf2png import render_pdf
from ai.tools.registry import register
from ai.tools.word2png import render_word
from ai.tools.word_doc import close as close_word
from ai.tools.word_doc import launch as launch_word

DOC_EXT = {".doc", ".docx"}
PDF_EXT = {".pdf"}
CAD_EXT = {".dwg", ".dxf", ".dwf"}
# 图纸位图（YOLO 版面检测与说明栏审查直接以 PNG 为输入）。图片本身就是一页，不需要转 PNG。
IMG_EXT = {".png", ".jpg", ".jpeg"}

CATALOG_ALIASES = [r"目录", r"content", r"contents", r"index", r"目次"]
PID_ALIASES = [r"p&id", r"pid", r"工艺自控", r"工艺控制", r"流程", r"pfd", r"uid"]
PLAN_ALIASES = [r"平面", r"总平", r"布置", r"layout", r"site", r"plot"]


def _norm(name: str) -> str:
    return re.sub(r"\s+", "", name.lower()).replace("（", "(").replace("）", ")")


def _match_alias(name: str, aliases: list[str]) -> bool:
    return any(re.search(pat, _norm(name)) for pat in aliases)


def _scan_dir(root: Path, base: Path) -> list[dict[str, str]]:
    files = []
    for path in sorted(root.iterdir()):
        if not path.is_file() or path.name.startswith("~$"):
            continue
        if path.suffix.lower() not in DOC_EXT | PDF_EXT | CAD_EXT | IMG_EXT:
            continue
        # name 用相对路径，子目录里的图也能用 folder / name 找到。
        rel = path.relative_to(base).as_posix()
        files.append({"id": path.stem, "name": rel, "path": str(path), "suffix": path.suffix.lower()})
    return files


def _list_folder(folder: str) -> list[dict[str, str]]:
    root = Path(folder)
    if not root.is_dir():
        return []
    files = _scan_dir(root, root)
    if files:
        return files
    # 顶层没有图纸时再看一层子目录，例如 天然气/清管站、天然气/集气站。
    for sub in sorted(root.iterdir()):
        if sub.is_dir() and not sub.name.startswith("."):
            files.extend(_scan_dir(sub, root))
    return files


def _render_first_page(item: dict[str, str], work: Path, dpi: int, app=None) -> str:
    suffix = item.get("suffix") or Path(item["name"]).suffix.lower()
    try:
        if suffix in IMG_EXT:
            return item["path"]
        if suffix in DOC_EXT:
            return (render_word(item["path"], work, dpi=dpi, app=app) or {}).get("image") or ""
        if suffix in PDF_EXT:
            return ((render_pdf(item["path"], work, dpi=dpi) or {}).get("images") or [""])[0]
    except Exception:
        return ""
    return ""


def _vlm_classify(image_path: str) -> dict[str, Any]:
    fields = [
        {"name": "is_catalog", "desc": "是否为资料图纸目录，true 或 false"},
        {"name": "is_pid", "desc": "是否为工艺自控流程图(PID/P&ID)，true 或 false"},
        {"name": "is_plan", "desc": "是否为平面图/CAD图纸，true 或 false"},
        {"name": "confidence", "desc": "判断置信度，0 到 1 之间的小数"},
    ]
    data = extract_json(prompt_id="file_classify.classify", fields=fields, image_path=image_path)
    if data.get("_error"):
        return {"is_catalog": False, "is_pid": False, "is_plan": False, "confidence": 0.0}
    return {
        "is_catalog": bool(data.get("is_catalog")),
        "is_pid": bool(data.get("is_pid")),
        "is_plan": bool(data.get("is_plan")),
        "confidence": float(data.get("confidence") or 0),
    }


def find_catalog(
    files: list[dict[str, Any]],
    *,
    work_dir: Path,
    dpi: int = PDF_DPI,
    candidates: list[dict[str, Any]] | None = None,
    scope: str = "all",
    prompt: str = "file_classify.is_catalog",
    threshold: float = 0.8,
) -> tuple[dict[str, Any] | None, list[str]]:
    """在文件列表中找目录。供目录索引一致性复用。

    返回 (catalog_file, logs)。先按文件名匹配，未命中则转 PNG 送 VLM。
    """
    logs: list[str] = []
    pool = candidates if candidates is not None else files
    if scope == "word":
        pool = [f for f in pool if Path(f["name"]).suffix.lower() in DOC_EXT]
    elif scope == "pdf":
        pool = [f for f in pool if Path(f["name"]).suffix.lower() in PDF_EXT]

    hit = next((f for f in pool if _match_alias(f["name"], CATALOG_ALIASES)), None)
    if hit:
        logs.append(f"文件名命中目录：{hit['name']}")
        return hit, logs

    logs.append(f"文件名未命中目录，VLM 兜底，候选 {len(pool)} 个")
    fields = [
        {"name": "is_catalog", "desc": "该页是否为资料图纸目录，true 或 false"},
        {"name": "confidence", "desc": "判断置信度，0 到 1 之间的小数"},
    ]
    best: dict[str, Any] | None = None
    best_score = 0.0
    app = None
    try:
        for item in pool:
            suffix = item.get("suffix") or Path(item["name"]).suffix.lower()
            if suffix not in DOC_EXT | PDF_EXT:
                continue
            if suffix in DOC_EXT and app is None:
                app = launch_word()
            image = _render_first_page(item, work_dir, dpi, app=app)
            if not image:
                continue
            data = extract_json(prompt_id=prompt, fields=fields, image_path=image)
            if data.get("_error"):
                logs.append(f"{item['name']} 判定失败：{data['_error']}")
                continue
            score = float(data.get("confidence") or 0)
            if bool(data.get("is_catalog")) and score >= threshold and score >= best_score:
                best = item
                best_score = score
                logs.append(f"{item['name']} is_catalog=true conf={score:.2f}")
    finally:
        if app is not None:
            close_word(app)
    return best, logs


def classify_folder(
    folder: str,
    *,
    dpi: int = PDF_DPI,
    use_vlm: bool = True,
    threshold: float = 0.8,
) -> dict[str, Any]:
    """分类文件夹中的文件，返回 file_types 工件。"""
    files = _list_folder(folder)
    logs: list[str] = []
    work = WORK_ROOT / "classify"
    work.mkdir(parents=True, exist_ok=True)

    catalog_file = plan_file = None
    pid_files: list[dict[str, str]] = []

    for item in files:
        name = item["name"]
        if catalog_file is None and _match_alias(name, CATALOG_ALIASES):
            catalog_file = item
            logs.append(f"文件名命中目录：{name}")
        # PID 可能有多份，全部收下
        if _match_alias(name, PID_ALIASES):
            pid_files.append(item)
            logs.append(f"文件名命中PID：{name}")
        if plan_file is None and (item.get("suffix", Path(name).suffix.lower()) in CAD_EXT or _match_alias(name, PLAN_ALIASES)):
            plan_file = item
            logs.append(f"文件名/CAD后缀命中平面图：{name}")

    if use_vlm:
        need = {"catalog": catalog_file is None, "plan": plan_file is None}
        scan_pid = not pid_files
        if need["catalog"] or need["plan"] or scan_pid:
            named = {f["name"] for f in pid_files}
            candidates = [f for f in files if f["suffix"] in DOC_EXT | PDF_EXT | IMG_EXT and f["name"] not in named]
            logs.append(f"VLM 兜底判定，候选 {len(candidates)} 个文件")
            app = None
            try:
                if any(f["suffix"] in DOC_EXT for f in candidates):
                    app = launch_word()
                for item in candidates:
                    image = _render_first_page(item, work, dpi, app=app)
                    if not image:
                        continue
                    result = _vlm_classify(image)
                    conf = result.get("confidence", 0)
                    if conf < threshold:
                        continue
                    if need["catalog"] and result["is_catalog"]:
                        catalog_file = item
                        need["catalog"] = False
                        logs.append(f"VLM 判定目录：{item['name']} conf={conf:.2f}")
                    # PID 全部收下，不因命中一个就停
                    if scan_pid and result["is_pid"]:
                        pid_files.append(item)
                        logs.append(f"VLM 判定PID：{item['name']} conf={conf:.2f}")
                    if need["plan"] and result["is_plan"]:
                        plan_file = item
                        need["plan"] = False
                        logs.append(f"VLM 判定平面图：{item['name']} conf={conf:.2f}")
                    if not need["catalog"] and not need["plan"] and not scan_pid:
                        break
            finally:
                if app is not None:
                    close_word(app)

    return {
        "file_types": {
            "catalog": catalog_file["name"] if catalog_file else None,
            "pid": [f["name"] for f in pid_files],
            "plan": plan_file["name"] if plan_file else None,
            "all_files": [f["name"] for f in files],
            "logs": logs,
        }
    }


@register("extract.file_types", produces=["file_types"])
def run(files: list[dict[str, Any]], artifacts: dict[str, Any]) -> dict[str, Any]:
    """Tool 入口，供 registry 调度。从 files 推断 folder，返回 file_types 工件。"""
    folder = artifacts.get("folder") or ""
    if not folder and files:
        folder = str(Path(files[0].get("path") or "").parent)
    if not folder or not Path(folder).is_dir():
        return {"file_types": {"_stub": True, "catalog": None, "pid": [], "plan": None, "all_files": [], "logs": ["缺少 folder"]}}
    return classify_folder(folder)
