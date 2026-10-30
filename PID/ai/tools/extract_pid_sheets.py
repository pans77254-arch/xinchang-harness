"""抽取 PID 图纸各页页号。复用图框裁剪与信息抽取，只返回数据，不做连续性判断。

PID 文件名直接取自文件属性判断结果（artifacts.file_types.pid），本工具不重新分类。
每份 PID 都逐页处理，顺序：PNG → 倾斜校正 + 二值化 → YOLO 裁图框 → VLM 抽取。
预处理参数取 artifacts.preprocess.pid_sheets（由 Skill 的 preprocess 配置块注入）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai.agents.drawing_detect import crop_image
from ai.agents.extract_info import extract_json
from ai.config import PDF_DPI, WORK_ROOT
from ai.tools.image_preprocess import PARAMS, preprocess_image
from ai.tools.pdf2png import render_pdf
from ai.tools.registry import register

PDF_EXT = {".pdf"}
CATEGORY = "图框"
PROMPT_ID = "extract.pid_sheets"
FIELDS = [
    {"name": "drawing_no", "desc": "本页图号或文件号"},
    {"name": "name", "desc": "本页图名或资料名称"},
    {"name": "sheet_no", "desc": "本页页码或序号，照抄原文，如 3、03、第3页、共8页第3页"},
    {"name": "total_sheets", "desc": "本页标注的总页数，取「共 X 页」中的 X"},
]


def _as_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _folder(files: list[dict[str, Any]], artifacts: dict[str, Any]) -> str:
    folder = str(artifacts.get("folder") or "")
    if folder:
        return folder
    if files:
        return str(Path(files[0].get("path") or "").parent)
    return ""


def _pid_names(artifacts: dict[str, Any]) -> list[str]:
    """文件属性判断给出的 PID 文件名，可能有多份。"""
    value = (artifacts.get("file_types") or {}).get("pid")
    if not isinstance(value, list):
        return []
    return [name for name in (_as_text(v) for v in value) if name]


def _pre_params(artifacts: dict[str, Any]) -> dict[str, Any]:
    """取本工具对应的预处理配置，多余键忽略。"""
    block = (artifacts.get("preprocess") or {}).get("pid_sheets") or {}
    if not isinstance(block, dict):
        return {}
    return {key: block[key] for key in PARAMS if key in block}


def _prepared_image(image: str, work_dir: Path, logs: list[str], pre_params: dict[str, Any]) -> str:
    """先倾斜校正 + 二值化；失败用原图兜底，不中断。"""
    if not pre_params:
        return image
    try:
        result = preprocess_image(image, work_dir / "preprocessed", **pre_params)
    except Exception as exc:
        logs.append(f"extract.pid_sheets: 预处理异常，用原图：{exc}")
        return image
    logs.extend(result.get("logs") or [])
    if result.get("ok") and result.get("out_path"):
        return str(result["out_path"])
    logs.append(f"extract.pid_sheets: 预处理失败，用原图：{result.get('error')}")
    return image


def _model_image(
    image: str,
    work_dir: Path,
    logs: list[str],
    name: str,
    pre_params: dict[str, Any],
) -> str:
    """预处理 → 裁图框；未检出时整页兜底，不中断。"""
    prepared = _prepared_image(image, work_dir, logs, pre_params)
    cropped = crop_image(prepared, work_dir / "crops", CATEGORY)
    if cropped.get("ok") and cropped.get("crop_path"):
        logs.append(f"extract.pid_sheets: yolo {name} 图框 conf={cropped.get('confidence')}")
        return str(cropped["crop_path"])
    logs.append(f"extract.pid_sheets: yolo {name} 未裁到图框，整页兜底：{cropped.get('error')}")
    return prepared


def _extract_one(name: str, folder: str, pre_params: dict[str, Any], logs: list[str]) -> dict[str, Any]:
    """逐页抽取一份 PID PDF，返回该文件的页号书册。单份失败不影响其他文件。"""
    book: dict[str, Any] = {"file": name, "pages_total": 0, "items": [], "errors": []}
    path = Path(folder) / name if folder else Path(name)
    if path.suffix.lower() not in PDF_EXT:
        error = f"{name} 不是 PDF 格式，本期仅支持 PDF 格式 PID"
        logs.append(f"extract.pid_sheets: {error}")
        return {**book, "errors": [error]}
    if not path.is_file():
        error = f"找不到 PID 文件 {path}"
        logs.append(f"extract.pid_sheets: {error}")
        return {**book, "errors": [error]}

    work_dir = WORK_ROOT / "pid_sheets" / path.stem
    try:
        rendered = render_pdf(path, work_dir / "png", dpi=PDF_DPI, all_pages=True)
    except Exception as exc:
        error = f"{name} 转 PNG 失败：{exc}"
        logs.append(f"extract.pid_sheets: {error}")
        return {**book, "errors": [error]}

    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, image in enumerate(rendered.get("images") or [], start=1):
        data = extract_json(
            prompt_id=PROMPT_ID,
            fields=FIELDS,
            image_path=_model_image(str(image), work_dir, logs, name, pre_params),
        )
        if data.get("_error"):
            errors.append(f"第 {index} 页：{data['_error']}")
            logs.append(f"extract.pid_sheets: {name} 第 {index} 页抽取失败")
            continue
        items.append(
            {
                "file": name,
                "page": index,
                "drawing_no": _as_text(data.get("drawing_no")),
                "name": _as_text(data.get("name")),
                "sheet_no": _as_text(data.get("sheet_no")),
                "total_sheets": _as_text(data.get("total_sheets")),
            }
        )
        logs.append(f"extract.pid_sheets: {name} 第 {index} 页 sheet_no={_as_text(data.get('sheet_no'))}")

    page_count = int(rendered.get("page_count") or len(rendered.get("images") or []))
    logs.append(f"extract.pid_sheets: {name} 共 {page_count} 页，抽出 {len(items)} 页，失败 {len(errors)} 页")
    return {"file": name, "pages_total": page_count, "items": items, "errors": errors}


@register("extract.pid_sheets", produces=["pid_sheets"])
def run(files: list[dict[str, Any]], artifacts: dict[str, Any]) -> dict[str, Any]:
    logs: list[str] = []
    names = _pid_names(artifacts)
    if not names:
        logs.append("extract.pid_sheets: 未识别到 PID 图纸，跳过")
        return {"pid_sheets": {"files": [], "logs": logs}}

    folder = _folder(files, artifacts)
    pre_params = _pre_params(artifacts)
    logs.append(f"extract.pid_sheets: PID 图纸 {'、'.join(names)}")
    logs.append(f"extract.pid_sheets: 预处理参数 {pre_params or '未配置，跳过预处理'}")

    books = [_extract_one(name, folder, pre_params, logs) for name in names]
    return {"pid_sheets": {"files": books, "logs": logs}}