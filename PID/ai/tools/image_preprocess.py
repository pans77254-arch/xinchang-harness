"""图像预处理：倾斜校正 + 二值化。

核心函数 preprocess_image() 直接被其他 Tool 调用（与 crop_image 同模式），
同时注册空壳 Tool image.preprocess 让框架可见。参数由 Skill 的 preprocess 配置块提供。

处理顺序固定：倾斜校正 → 去噪 → 二值化。先做几何变换再做阈值统计，
否则旋转产生的锯齿会被二值化放大。
角度约定：detect_skew 返回的就是「矫正角」，直接传给 rotate 即可摆正，
调用方一律不再自行取负号。skew_fixed 也按同一口径填写矫正角。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ai.tools.registry import register

# preprocess_image 允许的配置键，其余键忽略，避免 Skill 里多写一项就报错。
PARAMS = (
    "binarize",
    "threshold_method",
    "threshold_value",
    "deskew",
    "skew_mode",
    "skew_max",
    "skew_min",
    "skew_fixed",
)


@register("image.preprocess", produces=["preprocessed"])
def run(files: list[dict[str, Any]], artifacts: dict[str, Any]) -> dict[str, Any]:
    """空壳：预处理通过 preprocess_image() 函数调用，不通过 fill 调度。"""
    return {
        "preprocessed": {
            "_stub": True,
            "logs": ["image.preprocess: 通过函数调用，不通过 fill 调度"],
        }
    }


def _norm_angle(angle: float) -> float:
    """把角度归一到 (-90, 90]，直线没有方向，±180 是同一根线。"""
    while angle > 90.0:
        angle -= 180.0
    while angle <= -90.0:
        angle += 180.0
    return angle


def detect_skew(gray: np.ndarray, max_angle: float) -> float:
    """霍夫变换检测直线倾角，返回矫正角（度）——直接 rotate(angle) 即可摆正，检不出返回 0。"""
    import cv2

    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    threshold = max(80, gray.shape[1] // 8)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold)
    if lines is None:
        return 0.0
    angles: list[float] = []
    for item in lines[:400]:
        theta = float(item[0][1]) * 180.0 / np.pi  # 直线法线角，[0, 180)
        tilt = _norm_angle(90.0 - theta)
        if abs(tilt) <= max_angle:
            angles.append(tilt)
    if not angles:
        return 0.0
    return -float(np.median(angles))


def rotate(image: np.ndarray, angle: float, *, color: bool = True) -> np.ndarray:
    """逆时针旋转 angle 度，扩大画布避免裁切，空处填白。"""
    import cv2

    height, width = image.shape[:2]
    side = int(np.ceil(np.hypot(height, width)))
    matrix = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), angle, 1.0)
    matrix[0, 2] += (side - width) / 2.0
    matrix[1, 2] += (side - height) / 2.0
    border = (255, 255, 255) if color else 255
    return cv2.warpAffine(
        image,
        matrix,
        (side, side),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=border,
    )


def to_binary(gray: np.ndarray, method: str, threshold_value: int) -> np.ndarray:
    """按方法二值化，再开运算去掉孤立噪点。"""
    import cv2

    name = str(method or "otsu").lower()
    if name == "fixed":
        _, binary = cv2.threshold(gray, int(threshold_value), 255, cv2.THRESH_BINARY)
    elif name == "adaptive":
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10
        )
    else:
        name = "otsu"
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel = np.ones((2, 2), np.uint8)
    return cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)


def preprocess_image(
    image_path: str | Path,
    out_dir: str | Path,
    *,
    binarize: bool = True,
    threshold_method: str = "otsu",
    threshold_value: int = 127,
    deskew: bool = True,
    skew_mode: str = "auto",
    skew_max: float = 15.0,
    skew_min: float = 0.5,
    skew_fixed: float = 0.0,
) -> dict[str, Any]:
    """倾斜校正 + 二值化，返回处理后的图片路径。失败不抛异常。"""
    import cv2

    src = Path(image_path)
    logs: list[str] = []
    base: dict[str, Any] = {
        "ok": False,
        "out_path": "",
        "skew_angle": 0.0,
        "corrected": False,
        "threshold_method": "",
        "logs": logs,
    }
    image = cv2.imread(str(src), cv2.IMREAD_COLOR)
    if image is None:
        error = f"读图失败：{src}"
        logs.append(f"image.preprocess: {error}")
        return {**base, "error": error}
    if not deskew and not binarize:
        logs.append("image.preprocess: 未启用任何处理，返回原图")
        return {**base, "ok": True, "out_path": str(src)}

    angle = 0.0
    corrected = False
    if deskew:
        mode = str(skew_mode or "auto").lower()
        if mode == "fixed":
            angle = float(skew_fixed)
        elif mode == "auto":
            angle = detect_skew(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), float(skew_max))
        else:
            angle = 0.0
        if abs(angle) < float(skew_min):
            logs.append(f"image.preprocess: 倾斜 {angle:.2f}°，小于 {float(skew_min)}°，不矫正")
            angle = 0.0
        else:
            image = rotate(image, angle, color=True)
            corrected = True
            logs.append(f"image.preprocess: 倾斜 {angle:.2f}°，已矫正")
    else:
        logs.append("image.preprocess: 未启用倾斜校正")

    method = ""
    if binarize:
        method = str(threshold_method or "otsu").lower()
        gray = cv2.medianBlur(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), 3)
        binary = to_binary(gray, method, int(threshold_value))
        if method not in {"fixed", "adaptive"}:
            method = "otsu"
        image = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        logs.append(f"image.preprocess: 二值化 method={method}")
    else:
        logs.append("image.preprocess: 未启用二值化")

    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"{src.stem}_preprocessed.png"
    if not cv2.imwrite(str(out), image):
        error = f"写图失败：{out}"
        logs.append(f"image.preprocess: {error}")
        return {**base, "error": error}
    logs.append(f"image.preprocess: 输出 {out}")
    return {
        **base,
        "ok": True,
        "out_path": str(out),
        "skew_angle": round(angle, 3),
        "corrected": corrected,
        "threshold_method": method,
    }