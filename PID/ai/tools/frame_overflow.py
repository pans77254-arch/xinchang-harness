"""检查工艺图线是否越过绘图区。

绘图区是图框线内侧、再去掉说明、表格、图框这些专用区之后的范围。
专用区自己的线留在区内，不算越界。图线只要跨过边界就算超图框，不设长度或置信度门槛。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

ZONE_OUTSIDE = 1
ZONE_FRAME = 2
ZONE_NOTES = 3
ZONE_CHART = 4
ZONE_NAME = {ZONE_OUTSIDE: "图框外", ZONE_FRAME: "图框", ZONE_NOTES: "说明", ZONE_CHART: "表格"}


def _otsu(gray: np.ndarray) -> int:
    hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    if total <= 0:
        return 128
    prob = hist / total
    omega = np.cumsum(prob)
    mu = np.cumsum(prob * np.arange(256))
    mu_t = mu[-1]
    denom = omega * (1 - omega)
    sigma = np.zeros(256)
    valid = denom > 0
    sigma[valid] = (mu_t * omega[valid] - mu[valid]) ** 2 / denom[valid]
    return int(np.argmax(sigma))


def _pool_any(ink: np.ndarray, factor: int) -> np.ndarray:
    if factor <= 1:
        return ink
    height, width = ink.shape
    height2, width2 = height // factor, width // factor
    cropped = ink[: height2 * factor, : width2 * factor]
    return cropped.reshape(height2, factor, width2, factor).any(axis=(1, 3))


def _longest_run(row: np.ndarray) -> int:
    if not row.any():
        return 0
    padded = np.concatenate(([False], row, [False]))
    changes = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1)
    if starts.size == 0:
        return 0
    return int((ends - starts).max())


def _inner_frame(ink: np.ndarray) -> tuple[int, int, int, int] | None:
    """图框线的内沿。返回绘图内容可出现的 y0,x0,y1,x1，右下为开区间。"""
    height, width = ink.shape
    if height < 20 or width < 20:
        return None
    row_score = np.array([_longest_run(ink[y]) for y in range(height)])
    col_score = np.array([_longest_run(ink[:, x]) for x in range(width)])
    row_cut = max(int(width * 0.55), 1)
    col_cut = max(int(height * 0.55), 1)
    rows = np.flatnonzero(row_score >= row_cut)
    cols = np.flatnonzero(col_score >= col_cut)
    if rows.size < 2 or cols.size < 2:
        return None
    top_band = rows[rows < height * 0.25]
    bottom_band = rows[rows > height * 0.75]
    left_band = cols[cols < width * 0.25]
    right_band = cols[cols > width * 0.75]
    if top_band.size == 0 or bottom_band.size == 0 or left_band.size == 0 or right_band.size == 0:
        return None
    y0 = int(top_band.max()) + 1
    y1 = int(bottom_band.min())
    x0 = int(left_band.max()) + 1
    x1 = int(right_band.min())
    if y1 - y0 < height * 0.4 or x1 - x0 < width * 0.4:
        return None
    return y0, x0, y1, x1


def _ncc_peak(page: np.ndarray, crop: np.ndarray) -> tuple[int, int, float]:
    """归一化相关的最高点。裁图是整页里的一块时，峰值应接近 1。"""
    page_f = page.astype(np.float32)
    crop_f = crop.astype(np.float32)
    ph, pw = page_f.shape
    ch, cw = crop_f.shape
    crop_zm = crop_f - float(crop_f.mean())
    energy = float(np.sum(crop_zm * crop_zm))
    if energy <= 0 or ch > ph or cw > pw:
        return 0, 0, 0.0
    corr = np.fft.irfft2(np.fft.rfft2(page_f) * np.conj(np.fft.rfft2(crop_zm[::-1, ::-1], page_f.shape)))
    corr = corr[: ph - ch + 1, : pw - cw + 1]
    sat = np.pad(page_f, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    local_sum = sat[ch:, cw:] - sat[:-ch, cw:] - sat[ch:, :-cw] + sat[:-ch, :-cw]
    sat2 = np.pad(page_f * page_f, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    local_sq = sat2[ch:, cw:] - sat2[:-ch, cw:] - sat2[ch:, :-cw] + sat2[:-ch, :-cw]
    local_energy = np.maximum(local_sq - (local_sum * local_sum) / float(ch * cw), 0.0)
    ncc = corr / np.sqrt(local_energy * energy + 1e-6)
    y, x = np.unravel_index(int(np.argmax(ncc)), ncc.shape)
    return int(y), int(x), float(ncc[y, x])


def _locate_crop(page: np.ndarray, crop: np.ndarray) -> tuple[int, int] | None:
    """裁图是页图上的一块，找回它的左上角。像素对不上就不用这块。"""
    if crop.ndim != 2 or page.ndim != 2:
        return None
    ch, cw = crop.shape
    ph, pw = page.shape
    if ch < 8 or cw < 8 or ch > ph or cw > pw:
        return None
    factor = 4
    y_s, x_s, score = _ncc_peak(page[::factor, ::factor], crop[::factor, ::factor])
    if score < 0.85:
        return None
    y0, x0 = y_s * factor, x_s * factor
    best: tuple[int, int] | None = None
    for dy in range(-factor, factor + 1):
        for dx in range(-factor, factor + 1):
            y, x = y0 + dy, x0 + dx
            if y < 0 or x < 0 or y + ch > ph or x + cw > pw:
                continue
            if np.array_equal(page[y : y + ch, x : x + cw], crop):
                best = (y, x)
                break
        if best is not None:
            break
    return best


def _runs(row: np.ndarray) -> list[tuple[int, int]]:
    if not row.any():
        return []
    padded = np.concatenate(([False], row, [False]))
    changes = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1)
    return [(int(a), int(b)) for a, b in zip(starts, ends)]


def _ruled_blocks(ink: np.ndarray, frame: tuple[int, int, int, int]) -> list[tuple[str, int, int, int, int]]:
    """图框线内侧的表格线网格。右下角贴着底边的一块视为图框，其余视为表格。"""
    y0, x0, y1, x1 = frame
    width = max(1, x1 - x0)
    min_len = max(24, int(width * 0.08))
    max_len = int(width * 0.55)
    segments: list[tuple[int, int, int]] = []
    for y in range(y0, y1):
        for start, end in _runs(ink[y, x0:x1]):
            length = end - start
            if min_len <= length <= max_len:
                segments.append((y, x0 + start, x0 + end))
    clusters: list[dict[str, int]] = []
    for y, left, right in segments:
        placed = False
        for cluster in clusters:
            if y - cluster["y1"] > 90:
                continue
            overlap = min(right, cluster["x1"]) - max(left, cluster["x0"])
            narrow = min(right - left, cluster["x1"] - cluster["x0"])
            if narrow <= 0 or overlap < narrow * 0.6:
                continue
            cluster["y1"] = y
            cluster["x0"] = min(cluster["x0"], left)
            cluster["x1"] = max(cluster["x1"], right)
            cluster["n"] += 1
            placed = True
            break
        if not placed:
            clusters.append({"y0": y, "y1": y, "x0": left, "x1": right, "n": 1})
    blocks = [item for item in clusters if item["n"] >= 4 and item["y1"] > item["y0"]]
    merged: list[dict[str, int]] = []
    for item in sorted(blocks, key=lambda block: block["y0"]):
        host = None
        for cluster in merged:
            overlap = min(item["x1"], cluster["x1"]) - max(item["x0"], cluster["x0"])
            narrow = min(item["x1"] - item["x0"], cluster["x1"] - cluster["x0"])
            if item["y0"] - cluster["y1"] <= 180 and narrow > 0 and overlap >= narrow * 0.7:
                host = cluster
                break
        if host is None:
            merged.append(dict(item))
            continue
        host["y1"] = max(host["y1"], item["y1"])
        host["x0"] = min(host["x0"], item["x0"])
        host["x1"] = max(host["x1"], item["x1"])
        host["n"] += item["n"]
    span_w = max(1, x1 - x0)
    span_h = max(1, y1 - y0)
    blocks = [
        item
        for item in merged
        if item["y1"] - item["y0"] >= 60
        and (
            item["x0"] >= x0 + int(span_w * 0.58)
            or (item["y0"] >= y0 + int(span_h * 0.62) and item["x1"] >= x0 + int(span_w * 0.7))
        )
    ]
    if not blocks:
        return []
    title = max(blocks, key=lambda item: (item["y1"], item["x1"]))
    found: list[tuple[str, int, int, int, int]] = []
    for item in blocks:
        if item is title and item["y1"] >= y0 + int((y1 - y0) * 0.7):
            label = "图框"
        elif item["y0"] <= y0 + int((y1 - y0) * 0.45):
            label = "说明"
        else:
            label = "表格"
        found.append((label, item["y0"], item["x0"], item["y1"] + 1, item["x1"]))
    return found


def _zone_intrusion(
    ink: np.ndarray,
    frame: tuple[int, int, int, int],
    blocks: list[tuple[str, int, int, int, int]],
) -> set[int]:
    """图线贴进右侧说明、表格或图框，中间没有空带，即算进入该区。

    只看这些区域自己的左边界，不把它们的宽度再向左扩一截。
    """
    _y0, x0, _y1, x1 = frame
    span = max(1, x1 - x0)
    codes = {"图框": ZONE_FRAME, "说明": ZONE_NOTES, "表格": ZONE_CHART}
    found: set[int] = set()
    strip = max(4, int(span * 0.08))
    for label, top, left, bottom, right in blocks:
        if right < x0 + int(span * 0.6) or bottom - top < 8 or left - strip < x0:
            continue
        band = ink[top:bottom, left - strip : left]
        if band.size == 0:
            continue
        rows = band.mean(axis=1)
        if float((rows > 0.15).mean()) >= 0.1:
            found.add(codes.get(label, ZONE_CHART))
    return found


def _neighbor_or(mask: np.ndarray) -> np.ndarray:
    out = np.zeros_like(mask)
    out[1:] |= mask[:-1]
    out[:-1] |= mask[1:]
    out[:, 1:] |= mask[:, :-1]
    out[:, :-1] |= mask[:, 1:]
    return out


def _crossed_zones(ink: np.ndarray, drawing: np.ndarray, forbidden: np.ndarray, wall: np.ndarray, zones: np.ndarray) -> set[int]:
    ink_d = ink & drawing
    ink_f = ink & forbidden
    found: set[int] = set()
    pairs = (
        (ink_d[:, :-1], ink_f[:, 1:], zones[:, 1:]),
        (ink_d[:, 1:], ink_f[:, :-1], zones[:, :-1]),
        (ink_d[:-1, :], ink_f[1:, :], zones[1:, :]),
        (ink_d[1:, :], ink_f[:-1, :], zones[:-1, :]),
    )
    for left, right, zone in pairs:
        hit = left & right
        if hit.any():
            found.update(int(v) for v in np.unique(zone[hit]) if int(v))
    ink_w = ink & wall
    if ink_w.any():
        bridged = ink_w & _neighbor_or(ink_d) & _neighbor_or(ink_f)
        if bridged.any():
            near = _neighbor_or(bridged) & ink_f
            found.update(int(v) for v in np.unique(zones[near]) if int(v))
    return found


def _load_gray(path: str) -> np.ndarray | None:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    file = Path(path)
    if not file.is_file():
        return None
    return np.asarray(Image.open(file).convert("L"))


def check_page(image_path: str, reserved: list[tuple[str, str]]) -> dict[str, Any]:
    """返回越界到了哪些区域。定不出图框线时 ok 为 False。"""
    gray = _load_gray(image_path)
    if gray is None:
        return {"ok": False, "error": "没有页图", "zones": []}
    ink_full = gray <= _otsu(gray)
    factor = 2
    ink = _pool_any(ink_full, factor)
    frame = _inner_frame(ink)
    if frame is None:
        return {"ok": False, "error": "没有找到图框线", "zones": []}
    y0, x0, y1, x1 = frame
    height, width = ink.shape
    zones = np.zeros(ink.shape, dtype=np.uint8)
    zones[:y0, :] = ZONE_OUTSIDE
    zones[y1:, :] = ZONE_OUTSIDE
    zones[:, :x0] = ZONE_OUTSIDE
    zones[:, x1:] = ZONE_OUTSIDE
    wall = np.zeros(ink.shape, dtype=bool)
    for y in range(max(0, y0 - 3), min(height, y0)):
        if _longest_run(ink[y]) >= int(width * 0.55):
            wall[y] = True
            zones[y] = 0
    for y in range(max(0, y1), min(height, y1 + 3)):
        if _longest_run(ink[y]) >= int(width * 0.55):
            wall[y] = True
            zones[y] = 0
    for x in range(max(0, x0 - 3), min(width, x0)):
        if _longest_run(ink[:, x]) >= int(height * 0.55):
            wall[:, x] = True
            zones[:, x] = 0
    for x in range(max(0, x1), min(width, x1 + 3)):
        if _longest_run(ink[:, x]) >= int(height * 0.55):
            wall[:, x] = True
            zones[:, x] = 0

    code = {"图框": ZONE_FRAME, "说明": ZONE_NOTES, "表格": ZONE_CHART}
    rects: list[tuple[int, int, int, int]] = []
    ruled = _ruled_blocks(ink, frame)
    for label, top, left, bottom, right in ruled:
        zones[top:bottom, left:right] = code.get(label, ZONE_CHART)
        rects.append((top, left, bottom, right))
    for label, crop_path in reserved:
        crop = _load_gray(crop_path)
        if crop is None:
            continue
        origin = _locate_crop(gray, crop)
        if origin is None:
            continue
        top, left = origin[0] // factor, origin[1] // factor
        bottom = min(height, (origin[0] + crop.shape[0]) // factor)
        right = min(width, (origin[1] + crop.shape[1]) // factor)
        if bottom <= top or right <= left:
            continue
        zones[top:bottom, left:right] = code.get(label, ZONE_FRAME)
        rects.append((top, left, bottom, right))

    # 专用区自己的边线算在区内，不把它和区内表格线的接触当成越界。
    for top, left, bottom, right in rects:
        rim = 4
        band = np.zeros(ink.shape, dtype=bool)
        band[top:bottom, left:right] = True
        inner = np.zeros(ink.shape, dtype=bool)
        inner[top + rim : max(top + rim, bottom - rim), left + rim : max(left + rim, right - rim)] = True
        wall |= band & ~inner
    zones[wall] = 0

    drawing = zones == 0
    drawing[:y0, :] = False
    drawing[y1:, :] = False
    drawing[:, :x0] = False
    drawing[:, x1:] = False
    drawing[wall] = False
    forbidden = zones > 0
    found = _crossed_zones(ink, drawing, forbidden, wall, zones)
    found.update(_zone_intrusion(ink, frame, ruled))
    return {"ok": True, "error": "", "zones": [ZONE_NAME[item] for item in sorted(found) if item in ZONE_NAME]}
