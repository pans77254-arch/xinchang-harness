"""按页面毫米尺寸判断图幅。边可以横放或竖放。"""

from __future__ import annotations

# 长边、短边，毫米。允许印刷和导出带来的少量偏差。
_SIZES = (
    ("A1", 841.0, 594.0),
    ("A3", 420.0, 297.0),
    ("A4", 297.0, 210.0),
)
_TOLERANCE_MM = 8.0


def measure_mm(width_mm: float, height_mm: float) -> dict[str, object]:
    """按显示后的宽高（毫米）判断图幅。边可以横放或竖放。"""
    width = float(width_mm)
    height = float(height_mm)
    short, long = sorted((width, height))
    size = ""
    for name, long_mm, short_mm in _SIZES:
        if abs(long - long_mm) <= _TOLERANCE_MM and abs(short - short_mm) <= _TOLERANCE_MM:
            size = name
            break
    return {
        "width_mm": round(width, 1),
        "height_mm": round(height, 1),
        "size": size,
    }


def measure_page(page) -> dict[str, object]:
    """fitz 页面。宽高按页面显示方向，已经计入旋转。"""
    width = float(page.rect.width) * 25.4 / 72
    height = float(page.rect.height) * 25.4 / 72
    return measure_mm(width, height)
