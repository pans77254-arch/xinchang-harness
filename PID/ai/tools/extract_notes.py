"""抽取 PID 图纸「说明」区域的文本行。只抄写，不判断错别字。

流程：PID 文件（PNG 直接用；PDF 先转 PNG）→ 版面 YOLO 检出全部「说明」框 → 裁图
→ 过高的裁图纵向切条 → 每条送 VLM 抄写 → 合并为 notes 工件。

检测来源由 NOTES_DETECT_SOURCE 决定：
- remote：SSH 到 GPU 服务器跑版面 YOLO，权重不下载，只收回「说明」框，本地裁图。
- yolo：本机权重 YOLO_WEIGHTS_LAYOUT。本机没有权重但配了远程主机时，自动改走 remote。
- label_json（开发态）：读与图片同名的 X-AnyLabeling JSON 里 label=="说明" 的框。
远程或本机都没检出时，退到标注 JSON。

PID 文件名取自 artifacts.file_types.pid；没有分类结果时按扩展名 + 文件名别名兜底。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ai.agents.drawing_detect import crop_all, crop_boxes
from ai.agents.extract_info import extract_json
from ai.config import (
    NOTES_DETECT_SOURCE,
    NOTES_STRIP_HEIGHT,
    NOTES_STRIP_OVERLAP,
    NOTES_VLM_MAX_SIDE,
    PDF_DPI,
    WORK_ROOT,
    YOLO_CONF_NOTES,
    YOLO_IMGSZ_LAYOUT,
    YOLO_WEIGHTS_LAYOUT,
)
from ai.tools.pdf2png import render_pdf
from ai.tools.registry import register

IMG_EXT = {".png", ".jpg", ".jpeg"}
PDF_EXT = {".pdf"}
CATEGORY = "说明栏"
LABEL_NAME = "说明"
PROMPT_ID = "extract.notes"
FIELDS = [
    {"name": "lines", "desc": "文本行数组，每项含 no（编号原文）、kind（条文|框图节点|图例|表格|标题）、text（原文）"},
]
KINDS = {"条文", "框图节点", "图例", "表格", "标题"}
WATERMARK_HINTS = ("内部文件", "请勿外传")
PID_ALIASES = [r"p&id", r"pid", r"工艺自控", r"工艺控制", r"流程", r"pfd", r"uid"]

# 图号段里的专业代码：GP 天然气（集气）、OP 石油（油气处理）、WP 给排水（水处理）。
_DISCIPLINE_CODES = {"GP": "GP", "OP": "OP", "WP": "WP"}
# 老式图号前缀：集-xxxxx 为天然气集输，水-xxxxx 为给排水。
_DISCIPLINE_PREFIX = {"集": "GP", "水": "WP", "油": "OP"}
_DRAWING_NO_PATTERNS = [
    # DD26044-GP-PID-001 / CEDC016S-2024-001-GP-DWG-001 / CEDC001S-2024-01-OP-PID-001 / DD26002-0601-OP-PID
    re.compile(r"[A-Z]{1,6}\d{3,6}[A-Z]?(?:-[A-Z0-9]+){2,6}"),
    # 集-39398／2 / 水-18448 / 水-18448_1
    re.compile(r"[集水油]-\d{4,6}(?:[／/]\d+)?"),
]


def _as_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _norm(name: str) -> str:
    return re.sub(r"\s+", "", name.lower()).replace("（", "(").replace("）", ")")


def _folder(files: list[dict[str, Any]], artifacts: dict[str, Any]) -> str:
    folder = str(artifacts.get("folder") or "")
    if folder:
        return folder
    if files:
        return str(Path(files[0].get("path") or "").parent)
    return ""


def _pid_names(files: list[dict[str, Any]], artifacts: dict[str, Any]) -> list[str]:
    """优先用文件属性判断结果；没有时按扩展名 + 文件名别名兜底。"""
    value = (artifacts.get("file_types") or {}).get("pid")
    names = [name for name in (_as_text(v) for v in (value if isinstance(value, list) else [])) if name]
    if names:
        return names
    fallback: list[str] = []
    for item in files:
        name = _as_text(item.get("name"))
        if Path(name).suffix.lower() in IMG_EXT | PDF_EXT and any(re.search(p, _norm(name)) for p in PID_ALIASES):
            fallback.append(name)
    return fallback


def drawing_no_of(name: str) -> str:
    """从文件名里取图号。取不到返回空字符串，不猜。"""
    stem = Path(name).stem
    for pattern in _DRAWING_NO_PATTERNS:
        found = pattern.search(stem)
        if found:
            return found.group(0).replace("／", "/")
    return ""


def discipline_of(name: str, drawing_no: str = "") -> str:
    """专业代码：GP | OP | WP | UNK。先看图号段，再看老式前缀，最后看文件名关键词。"""
    text = drawing_no or drawing_no_of(name)
    found = re.search(r"-(GP|OP|WP)(?:-|$)", text.upper())
    if found:
        return _DISCIPLINE_CODES[found.group(1)]
    if text[:1] in _DISCIPLINE_PREFIX:
        return _DISCIPLINE_PREFIX[text[:1]]
    lowered = name.lower()
    if any(k in lowered for k in ("采出水", "注水", "回注", "给排水", "水处理")):
        return "WP"
    if any(k in lowered for k in ("集气", "清管", "天然气", "净化")):
        return "GP"
    if any(k in lowered for k in ("增压", "脱水", "联合站", "原油", "接转")):
        return "OP"
    return "UNK"


def _page_images(path: Path, work_dir: Path) -> tuple[list[str], str]:
    """图片直接用；PDF 逐页转 PNG。返回 (图片列表, 错误)。"""
    suffix = path.suffix.lower()
    if suffix in IMG_EXT:
        return [str(path)], ""
    if suffix in PDF_EXT:
        rendered = render_pdf(path, work_dir / "png", dpi=PDF_DPI, all_pages=True)
        return [str(p) for p in (rendered.get("images") or [])], ""
    return [], f"{path.name} 不是图片或 PDF，说明栏抽取仅支持这两类"


def _label_json_boxes(image: Path) -> list[dict[str, Any]]:
    """读同名 X-AnyLabeling JSON 里的「说明」框。"""
    sidecar = image.with_suffix(".json")
    if not sidecar.is_file():
        return []
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return []
    boxes: list[dict[str, Any]] = []
    for shape in data.get("shapes") or []:
        if _as_text(shape.get("label")) != LABEL_NAME:
            continue
        points = shape.get("points") or []
        xs = [float(p[0]) for p in points if len(p) >= 2]
        ys = [float(p[1]) for p in points if len(p) >= 2]
        if len(xs) < 2:
            continue
        boxes.append({"bbox": [min(xs), min(ys), max(xs), max(ys)], "confidence": shape.get("score")})
    return boxes


def _detect(image: Path, work_dir: Path, logs: list[str]) -> tuple[list[dict[str, Any]], str, str]:
    """检出说明框并裁剪。返回 (crops, source, error)。"""
    from ai.tools.remote_yolo import predict_remote, remote_enabled

    crops_dir = work_dir / "crops"
    source_mode = NOTES_DETECT_SOURCE
    if source_mode == "yolo" and not YOLO_WEIGHTS_LAYOUT.is_file() and remote_enabled():
        source_mode = "remote"
    if source_mode == "remote":
        try:
            boxes = predict_remote(image, imgsz=YOLO_IMGSZ_LAYOUT, conf=YOLO_CONF_NOTES)
        except Exception as exc:
            logs.append(f"extract.notes: remote {image.name} 失败：{exc}")
            boxes = []
        if boxes:
            scores = "、".join(str(box.get("confidence")) for box in boxes)
            logs.append(f"extract.notes: remote {image.name} 说明框 {len(boxes)} 个 conf={scores}")
            return crop_boxes(image, crops_dir, boxes, class_name=LABEL_NAME), "yolo_remote", ""
        logs.append(f"extract.notes: remote {image.name} 未检出说明框")
    elif source_mode != "label_json":
        result = crop_all(
            image,
            crops_dir,
            CATEGORY,
            weights=YOLO_WEIGHTS_LAYOUT,
            imgsz=YOLO_IMGSZ_LAYOUT,
            conf=YOLO_CONF_NOTES,
        )
        if result.get("ok"):
            scores = "、".join(str(c.get("confidence")) for c in result["crops"])
            logs.append(f"extract.notes: yolo {image.name} 说明框 {len(result['crops'])} 个 conf={scores}")
            return result["crops"], "yolo", ""
        logs.append(f"extract.notes: yolo {image.name} 未得到说明框：{result.get('error')}")
        # 权重缺失或未检出都退到标注 JSON，有就用，没有就报错。
    boxes = _label_json_boxes(image)
    if boxes:
        logs.append(f"extract.notes: label_json {image.name} 说明框 {len(boxes)} 个")
        return crop_boxes(image, crops_dir, boxes, class_name=LABEL_NAME), "label_json", ""
    return [], "", f"{image.name} 未找到说明栏（YOLO 未检出且无同名标注）"


def _strips(crop_path: str, work_dir: Path) -> list[str]:
    """裁图过高时纵向切条，相邻条带重叠一部分避免切断行。"""
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    image = Image.open(crop_path).convert("RGB")
    width, height = image.size
    # 超出阈值不到 20% 不切：多一次模型调用只为几百像素的尾巴不划算，max_side 足够容纳。
    if height <= int(NOTES_STRIP_HEIGHT * 1.2):
        return [crop_path]
    overlap = int(NOTES_STRIP_HEIGHT * NOTES_STRIP_OVERLAP)
    step = max(1, NOTES_STRIP_HEIGHT - overlap)
    count = max(2, -(-(height - overlap) // step))  # ceil
    # 均分条高，避免最后一条只剩一小截。
    strip = -(-(height + overlap * (count - 1)) // count)
    out_dir = work_dir / "strips"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(crop_path).stem
    paths: list[str] = []
    for index in range(count):
        top = max(0, index * (strip - overlap))
        bottom = height if index == count - 1 else min(height, top + strip)
        out = out_dir / f"{stem}-s{index + 1}.png"
        image.crop((0, top, width, bottom)).save(out)
        paths.append(str(out))
        if bottom >= height:
            break
    return paths


def _clean_lines(raw: Any) -> list[dict[str, str]]:
    """规范化模型返回的行：丢水印、丢空行、kind 收敛到枚举。"""
    lines: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return lines
    for entry in raw:
        if isinstance(entry, str):
            entry = {"text": entry}
        if not isinstance(entry, dict):
            continue
        text = re.sub(r"\s+", " ", _as_text(entry.get("text")))
        if not text or any(hint in text for hint in WATERMARK_HINTS):
            continue
        kind = _as_text(entry.get("kind"))
        if kind not in KINDS:
            kind = "条文"
        lines.append({"no": _as_text(entry.get("no")), "kind": kind, "text": text})
    return lines


def _merge(parts: list[list[dict[str, str]]]) -> list[dict[str, str]]:
    """合并切条结果。相邻条带重叠区会重复抄到同一行，去掉后一条开头与前一条结尾重复的行。"""
    merged: list[dict[str, str]] = []
    for lines in parts:
        tail = {line["text"] for line in merged[-4:]}
        skipping = True
        for line in lines:
            if skipping and line["text"] in tail:
                continue
            skipping = False
            merged.append(line)
    for index, line in enumerate(merged, start=1):
        line["line"] = index  # type: ignore[assignment]
    return merged


def _transcribe(crop: dict[str, Any], work_dir: Path, logs: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    parts: list[list[dict[str, str]]] = []
    errors: list[str] = []
    strips = _strips(str(crop["crop_path"]), work_dir)
    if len(strips) > 1:
        logs.append(f"extract.notes: {Path(crop['crop_path']).name} 切为 {len(strips)} 条")
    for index, strip in enumerate(strips, start=1):
        data = extract_json(
            prompt_id=PROMPT_ID,
            fields=FIELDS,
            image_path=strip,
            max_side=NOTES_VLM_MAX_SIDE,
            max_tokens=8192,
        )
        if data.get("_error"):
            errors.append(f"{Path(strip).name}：{data['_error']}")
            logs.append(f"extract.notes: 第 {index} 条抄写失败：{data['_error']}")
            continue
        lines = _clean_lines(data.get("lines"))
        logs.append(f"extract.notes: 第 {index} 条抄出 {len(lines)} 行")
        parts.append(lines)
    return _merge(parts), errors


def _extract_one(name: str, folder: str, logs: list[str]) -> dict[str, Any]:
    drawing_no = drawing_no_of(name)
    book: dict[str, Any] = {
        "file": name,
        "drawing_no": drawing_no,
        "discipline": discipline_of(name, drawing_no),
        "pages_total": 0,
        "items": [],
        "errors": [],
    }
    path = Path(folder) / name if folder else Path(name)
    if not path.is_file():
        error = f"找不到文件 {path}"
        logs.append(f"extract.notes: {error}")
        return {**book, "errors": [error]}

    # 文件名很长，且截断后可能以空格结尾，Windows 不能用这种目录名。
    stem = re.sub(r'[<>:"/\\|?*]', "_", path.stem).strip().rstrip(". ")[:40] or "drawing"
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:8]
    work_dir = WORK_ROOT / "notes" / f"{stem}-{digest}"
    try:
        images, error = _page_images(path, work_dir)
    except Exception as exc:
        error, images = f"{name} 转 PNG 失败：{exc}", []
    if error:
        logs.append(f"extract.notes: {error}")
        return {**book, "errors": [error]}

    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for page, image in enumerate(images, start=1):
        crops, source, error = _detect(Path(image), work_dir, logs)
        if error:
            errors.append(f"第 {page} 页：{error}")
            continue
        for crop in crops:
            lines, line_errors = _transcribe(crop, work_dir, logs)
            errors.extend(f"第 {page} 页 {e}" for e in line_errors)
            items.append(
                {
                    "page": page,
                    "bbox": crop.get("bbox"),
                    "source": source,
                    "yolo_conf": crop.get("confidence"),
                    "crop_path": crop.get("crop_path"),
                    "lines": lines,
                }
            )
    total_lines = sum(len(it["lines"]) for it in items)
    logs.append(f"extract.notes: {name} 共 {len(images)} 页，说明块 {len(items)} 个，抄出 {total_lines} 行，失败 {len(errors)} 处")
    return {**book, "pages_total": len(images), "items": items, "errors": errors}


NOTE_LABELS = {"说明", "说明栏"}


def transcribe_detections(
    folder: str,
    detections: list[dict[str, Any]],
    work_dir: Path,
) -> dict[str, Any]:
    """用已经检出的版面框抄写说明栏。不再跑 YOLO。"""
    logs: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in detections:
        grouped.setdefault(str(item.get("file") or ""), []).append(item)
    books: list[dict[str, Any]] = []
    crops_root = work_dir / "note_crops"
    for name, pages in grouped.items():
        drawing_no = drawing_no_of(name)
        book: dict[str, Any] = {
            "file": name,
            "drawing_no": drawing_no,
            "discipline": discipline_of(name, drawing_no),
            "pages_total": len(pages),
            "items": [],
            "errors": [],
        }
        for page in pages:
            page_no = page.get("page") or 0
            if page.get("error"):
                book["errors"].append(f"第 {page_no} 页：{page['error']}")
                continue
            image = str(page.get("image") or "")
            image_path = Path(image)
            if folder and not image_path.is_file():
                image_path = Path(folder) / image
            boxes = [
                box
                for box in (page.get("boxes") or [])
                if str(box.get("class_name") or "") in NOTE_LABELS and box.get("bbox")
            ]
            if not image_path.is_file() or not boxes:
                book["errors"].append(f"第 {page_no} 页：未检出说明栏")
                continue
            crops = crop_boxes(image_path, crops_root, boxes, class_name=LABEL_NAME)
            logs.append(f"extract.notes: {Path(name).name} 第 {page_no} 页说明框 {len(crops)} 个")
            for crop in crops:
                lines, line_errors = _transcribe(crop, work_dir, logs)
                book["errors"].extend(f"第 {page_no} 页 {err}" for err in line_errors)
                book["items"].append(
                    {
                        "page": page_no,
                        "bbox": crop.get("bbox"),
                        "source": "layout",
                        "yolo_conf": crop.get("confidence"),
                        "crop_path": crop.get("crop_path"),
                        "lines": lines,
                    }
                )
        logs.append(
            f"extract.notes: {name} 说明块 {len(book['items'])} 个，"
            f"抄出 {sum(len(item['lines']) for item in book['items'])} 行"
        )
        books.append(book)
    return {"files": books, "logs": logs}


@register("extract.notes", produces=["notes"])
def run(files: list[dict[str, Any]], artifacts: dict[str, Any]) -> dict[str, Any]:
    logs: list[str] = []
    names = _pid_names(files, artifacts)
    if not names:
        logs.append("extract.notes: 未识别到 PID 图纸，跳过")
        return {"notes": {"files": [], "logs": logs}}
    folder = _folder(files, artifacts)
    logs.append(f"extract.notes: 检测来源 {NOTES_DETECT_SOURCE}，PID 图纸 {len(names)} 份")
    books = [_extract_one(name, folder, logs) for name in names]
    return {"notes": {"files": books, "logs": logs}}
