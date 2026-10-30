"""图纸识别智能体：输入图像和类别，输出裁剪图。

本审查点的类别是「图框」。权重 best.pt 的类别名是 title_block。
推理固定 imgsz=1280、conf=0.5。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai.config import CATEGORY_TO_CLASS, YOLO_CONF, YOLO_IMGSZ, YOLO_WEIGHTS

_MODEL = None
# 按权重路径缓存，图框权重与版面权重可同时加载。
_MODELS: dict[str, Any] = {}


def _model(weights: str | Path | None = None):
    """默认加载图框权重；传 weights 时加载指定权重并单独缓存。"""
    global _MODEL
    if weights is None:
        if _MODEL is None:
            _MODEL = _load(YOLO_WEIGHTS, "图框")
        return _MODEL
    key = str(Path(weights).resolve())
    if key not in _MODELS:
        _MODELS[key] = _load(Path(weights), "版面")
    return _MODELS[key]


def _load(path: Path, label: str):
    from ultralytics import YOLO

    if not path.is_file():
        raise FileNotFoundError(f"找不到{label}权重：{path}")
    return YOLO(str(path))


def _wanted_ids(model, category: str) -> tuple[set[int], str, str]:
    """类别名 → 权重里的类别 id 集合。返回 (ids, class_name, error)。"""
    class_name = CATEGORY_TO_CLASS.get(category, category)
    names = {int(k): str(v) for k, v in model.names.items()}
    wanted = {idx for idx, name in names.items() if name == class_name}
    if not wanted:
        known = "、".join(names.values()) or "无"
        return set(), class_name, f"权重中没有类别 {class_name}，现有：{known}"
    return wanted, class_name, ""


def _crop_box(image, xyxy: list[float]) -> Any:
    width, height = image.size
    x1, y1, x2, y2 = xyxy
    pad_x = max(8, int((x2 - x1) * 0.02))
    pad_y = max(8, int((y2 - y1) * 0.02))
    return image.crop(
        (
            max(0, int(x1) - pad_x),
            max(0, int(y1) - pad_y),
            min(width, int(x2) + pad_x),
            min(height, int(y2) + pad_y),
        )
    )


def crop_boxes(
    image_path: str | Path,
    out_dir: str | Path,
    boxes: list[dict[str, Any]],
    *,
    class_name: str = "box",
) -> list[dict[str, Any]]:
    """按给定框裁剪（框来自 YOLO 或人工标注均可）。boxes 每项至少含 bbox=[x1,y1,x2,y2]。

    返回与 crop_all 的 crops 同构：[{crop_path, confidence, bbox}]。
    """
    src = Path(image_path)
    dest_dir = Path(out_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    image = Image.open(src).convert("RGB")
    crops: list[dict[str, Any]] = []
    for index, box in enumerate(boxes, start=1):
        xyxy = [float(v) for v in box.get("bbox") or []]
        if len(xyxy) != 4:
            continue
        out = dest_dir / f"{src.stem}-{class_name}-{index}.png"
        _crop_box(image, xyxy).save(out)
        crops.append(
            {
                "crop_path": str(out),
                "confidence": box.get("confidence"),
                "bbox": [round(v, 1) for v in xyxy],
            }
        )
    return crops


def crop_all(
    image_path: str | Path,
    out_dir: str | Path,
    category: str = "说明栏",
    *,
    weights: str | Path | None = None,
    imgsz: int = YOLO_IMGSZ,
    conf: float = YOLO_CONF,
) -> dict[str, Any]:
    """检出指定类别的全部框并逐个裁剪，按置信度降序。

    与 crop_image 的区别：一页可能有多块说明栏，这里不取最高分那一个，而是全部返回。
    返回 {ok, category, class_name, crops: [{crop_path, confidence, bbox}], error}。
    """
    src = Path(image_path)
    dest_dir = Path(out_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    class_name = CATEGORY_TO_CLASS.get(category, category)
    try:
        model = _model(weights)
    except Exception as exc:
        return {"ok": False, "category": category, "class_name": class_name, "crops": [], "error": str(exc)}

    wanted, class_name, error = _wanted_ids(model, category)
    if error:
        return {"ok": False, "category": category, "class_name": class_name, "crops": [], "error": error}

    result = model.predict(source=str(src), imgsz=imgsz, conf=conf, verbose=False)[0]
    boxes = result.boxes
    found: list[tuple[float, list[float]]] = []
    if boxes is not None and len(boxes):
        for box in boxes:
            if int(box.cls[0]) not in wanted:
                continue
            found.append((float(box.conf[0]), [float(v) for v in box.xyxy[0].tolist()]))
    if not found:
        return {
            "ok": False,
            "category": category,
            "class_name": class_name,
            "crops": [],
            "error": f"未检出{category}（{class_name}，conf≥{conf}）",
        }

    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    image = Image.open(src).convert("RGB")
    crops: list[dict[str, Any]] = []
    for index, (score, xyxy) in enumerate(sorted(found, key=lambda item: -item[0]), start=1):
        out = dest_dir / f"{src.stem}-{class_name}-{index}.png"
        _crop_box(image, xyxy).save(out)
        crops.append({"crop_path": str(out), "confidence": round(score, 4), "bbox": [round(v, 1) for v in xyxy]})
    return {"ok": True, "category": category, "class_name": class_name, "crops": crops, "error": ""}


def crop_image(
    image_path: str | Path,
    out_dir: str | Path,
    category: str = "图框",
    *,
    imgsz: int = YOLO_IMGSZ,
    conf: float = YOLO_CONF,
) -> dict[str, Any]:
    """检出指定类别并裁剪置信度最高的一框。"""
    src = Path(image_path)
    dest_dir = Path(out_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    class_name = CATEGORY_TO_CLASS.get(category, category)
    try:
        model = _model()
    except Exception as exc:
        return {"ok": False, "category": category, "class_name": class_name, "error": str(exc)}

    names = {int(k): str(v) for k, v in model.names.items()}
    wanted = {idx for idx, name in names.items() if name == class_name}
    if not wanted:
        known = "、".join(names.values()) or "无"
        return {
            "ok": False,
            "category": category,
            "class_name": class_name,
            "error": f"权重中没有类别 {class_name}，现有：{known}",
        }

    result = model.predict(source=str(src), imgsz=imgsz, conf=conf, verbose=False)[0]
    boxes = result.boxes
    best = None
    if boxes is not None and len(boxes):
        for box in boxes:
            cls_id = int(box.cls[0])
            if cls_id not in wanted:
                continue
            score = float(box.conf[0])
            if best is None or score > best[0]:
                best = (score, [float(v) for v in box.xyxy[0].tolist()])

    if best is None:
        return {
            "ok": False,
            "category": category,
            "class_name": class_name,
            "confidence": 0.0,
            "error": f"未检出{category}（{class_name}，conf≥{conf}）",
        }

    score, xyxy = best
    from PIL import Image

    image = Image.open(src).convert("RGB")
    width, height = image.size
    x1, y1, x2, y2 = xyxy
    pad_x = max(8, int((x2 - x1) * 0.02))
    pad_y = max(8, int((y2 - y1) * 0.02))
    crop = image.crop(
        (
            max(0, int(x1) - pad_x),
            max(0, int(y1) - pad_y),
            min(width, int(x2) + pad_x),
            min(height, int(y2) + pad_y),
        )
    )
    out = dest_dir / f"{src.stem}-{class_name}.png"
    crop.save(out)
    return {
        "ok": True,
        "category": category,
        "class_name": class_name,
        "crop_path": str(out),
        "confidence": round(score, 4),
        "bbox": [round(v, 1) for v in xyxy],
        "error": "",
    }
