"""规则校验算子。审查点 YAML 只能引用这里已登记的 op，没有的先向平台申请。"""

from __future__ import annotations

import re
from typing import Any, Callable


def set_diff(left: list[str], right: list[str]) -> tuple[set[str], set[str]]:
    a, b = set(filter(None, left)), set(filter(None, right))
    return a - b, b - a


def eq_all(values: list[str]) -> tuple[bool, set[str]]:
    cleaned = {v.strip() for v in values if v and str(v).strip()}
    return len(cleaned) <= 1, cleaned


def revision_key(value: str) -> str:
    """版次比较用。0版、0、 0 版 视为同一个值。"""
    text = re.sub(r"\s+", "", str(value or ""))
    text = text.replace("版次", "")
    if text.endswith("版"):
        text = text[:-1]
    return text.upper()


def revision_conflicts(rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """同一图号前缀下版次不一致时，返回 (前缀, 说明)。"""
    groups: dict[str, list[tuple[str, str, str]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        number = str(row.get("文件号") or row.get("drawing_no") or "").strip()
        prefix = file_no_prefix(number) or number or str(row.get("file") or "")
        raw = str(row.get("版次") or "").strip()
        groups.setdefault(prefix, []).append((number or prefix, raw, revision_key(raw)))
    found: list[tuple[str, str]] = []
    for prefix, items in groups.items():
        filled = [(number, raw, key) for number, raw, key in items if key]
        keys = {key for _, _, key in filled}
        missing = [number for number, raw, key in items if not key]
        if len(keys) > 1:
            shown = "、".join(f"{number} 为 {raw}" for number, raw, _ in filled)
            found.append((prefix, f"版次不统一：{shown}"))
        elif keys and missing:
            shown = "、".join(missing)
            value = filled[0][1]
            found.append((prefix, f"版次不统一：{shown} 未填，其余为 {value}"))
    return found


def file_no_prefix(drawing_no: str) -> str:
    """去掉文件号最后一段纯数字，留下同组应一致的前缀。"""
    parts = [part for part in str(drawing_no or "").strip().split("-") if part != ""]
    if len(parts) >= 2 and parts[-1].isdigit():
        return "-".join(parts[:-1])
    return str(drawing_no or "").strip()


def sheet_count_of(text: str) -> int | None:
    """从「共 X 张」或纯数字里取出张数。没有数字返回 None。"""
    raw = str(text or "").strip()
    if not raw:
        return None
    matched = re.search(r"\d+", raw)
    if matched is None:
        return None
    return int(matched.group(0))


def survey_cert_problem(
    design_no: str,
    survey_no: str,
    discipline: str = "",
    certs: list[dict] | None = None,
) -> str:
    """按启用通知核对勘察证书号。专业能对上资质时，用该资质的 B 编号；对不上时，编号须是通知里的有效号，并与图上设计证书号同号。没问题返回空字符串。"""
    design = re.sub(r"\s+", "", str(design_no or ""))
    survey = re.sub(r"\s+", "", str(survey_no or ""))
    major = re.sub(r"\s+", "", str(discipline or ""))
    if not survey:
        return "为空"
    pairs = _survey_pairs(certs)
    if re.fullmatch(r"B\d{6,}", survey) is None:
        allowed = "、".join(item["survey"] for item in pairs) or "B 加至少 6 位数字"
        return f"错误：不在启用编号内，现在是 {survey}，有效编号为 {allowed}"
    expected = _survey_for_discipline(major, pairs)
    if expected:
        if survey != expected["survey"]:
            return (
                f"错误：专业「{major}」应使用 {expected['survey']}"
                f"（设计证书 {expected['design']}），现在是 {survey}"
            )
        return ""
    allowed = {item["survey"] for item in pairs}
    if pairs and survey not in allowed:
        shown = "、".join(item["survey"] for item in pairs)
        return f"错误：不在启用编号内，现在是 {survey}，有效编号为 {shown}"
    if re.fullmatch(r"A\d{6,}", design) and survey[1:] != design[1:]:
        return f"错误：应与设计证书号 {design} 对应为 B{design[1:]}，现在是 {survey}"
    return ""


def _survey_pairs(certs: list[dict] | None) -> list[dict]:
    pairs: list[dict] = []
    for item in certs or []:
        if not isinstance(item, dict):
            continue
        design = re.sub(r"\s+", "", str(item.get("design") or ""))
        survey = re.sub(r"\s+", "", str(item.get("survey") or ""))
        words = [re.sub(r"\s+", "", str(word)) for word in (item.get("keywords") or [])]
        words = [word for word in words if word]
        if design and survey:
            pairs.append({"design": design, "survey": survey, "keywords": words})
    return pairs


def _survey_for_discipline(discipline: str, pairs: list[dict]) -> dict | None:
    best: tuple[int, dict] | None = None
    for item in pairs:
        for word in item["keywords"]:
            if word and word in discipline and (best is None or len(word) > best[0]):
                best = (len(word), item)
    return None if best is None else best[1]


_DATE_RE = re.compile(r"^20\d{2}[.-]\d{1,2}[.-]\d{1,2}$")
_FILE_RE = re.compile(r"^(?:PP|SS|BF|BP|FS|CD|PA|BD|PD|DD|ST).+-\d+$")
_PROJECT_RE = re.compile(r"^CEDC\d{3}[CSQ]-\d{4}$")
_SCALE_RE = re.compile(r"^\d+\s*[:：]\s*\d+$|^[~～∼∽]+$|^见图$")
_DESIGN_CERT_RE = re.compile(r"^A\d{6,}$")
_REVISION_RE = re.compile(r"^(?:[A-Z]|[1-9]\d*[A-Z]?|0)版?$")
_STAGES = {"施工图", "初步设计"}
_UNIT_FIXES = (
    (re.compile(r"(?<![A-Za-z])Mpa(?![A-Za-z])"), "MPa"),
    (re.compile(r"(?<![A-Za-z])mpa(?![A-Za-z])"), "MPa"),
    (re.compile(r"(?<![A-Za-z0-9])m3(?![A-Za-z0-9])"), "m³"),
    (re.compile(r"(?<![A-Za-z0-9])m2(?![A-Za-z0-9])"), "m²"),
    (re.compile(r"mm3"), "mm³"),
    (re.compile(r"mm2"), "mm²"),
)


def field_format_problem(
    name: str,
    value: str,
    discipline: str = "",
    certs: list[dict] | None = None,
) -> str:
    """栏位有字但不符格式时返回原因。空值留给必填检查。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if name == "日期" and _DATE_RE.fullmatch(text) is None:
        return "应为阿拉伯数字年.月.日，如 2026.07.03"
    if name == "文件号" and _FILE_RE.fullmatch(text) is None:
        return "应以设计阶段代码开头、以文件序号结尾，如 DD25001-01-OP-PID-001"
    if name == "项目号" and _PROJECT_RE.fullmatch(re.sub(r"\s+", "", text)) is None:
        return "应为 CEDC、三位顺序号、阶段代号和年号，如 CEDC132S-2024"
    if name == "阶段" and text not in _STAGES:
        return "应为「初步设计」或「施工图」"
    if name == "比例" and _SCALE_RE.fullmatch(text) is None:
        return "应为 1:100 这类比例、无比例时的∽，或多比例时的见图"
    if name == "设计证书号":
        return _design_cert_problem(text, discipline, certs)
    if name == "版次" and _REVISION_RE.fullmatch(text.upper().replace(" ", "")) is None:
        return "应为过程版 A版、正式版 0版，或升版后的 1版、1A版"
    return ""


def _design_cert_problem(design_no: str, discipline: str, certs: list[dict] | None) -> str:
    """第11.2.2.4条：设计证书号必须对上该专业的启用编号。"""
    design = re.sub(r"\s+", "", str(design_no or ""))
    major = re.sub(r"\s+", "", str(discipline or ""))
    if _DESIGN_CERT_RE.fullmatch(design) is None:
        return "应为 A 加至少 6 位数字"
    pairs = _survey_pairs(certs)
    expected = _survey_for_discipline(major, pairs)
    if expected and design != expected["design"]:
        return f"错误：专业「{major}」应使用 {expected['design']}，现在是 {design}"
    allowed = [item["design"] for item in pairs]
    if allowed and design not in allowed:
        return f"错误：不在启用编号内，现在是 {design}，有效编号为 {'、'.join(allowed)}"
    return ""


def unit_format_hits(text: str) -> list[tuple[str, str]]:
    """说明文字里的单位和括号格式。返回 (错误片段, 应改成)。"""
    found: list[tuple[str, str]] = []
    for pattern, correct in _UNIT_FIXES:
        matched = pattern.search(text or "")
        if matched is not None:
            found.append((matched.group(0), correct))
    if text.count("（") != text.count("）") or text.count("(") != text.count(")"):
        found.append(("括号不成对", "补齐括号"))
    if "。。" in text or "，，" in text or ".." in text:
        found.append(("连续标点", "保留一个标点"))
    if re.search(r"(?<![A-Za-z])Kg(?![A-Za-z])", text) or re.search(r"(?<![A-Za-z])KG(?![A-Za-z])", text):
        found.append(("Kg", "kg"))
    return found


def name_overlap(item: dict[str, Any], fields: list[str], *, min_len: int = 4) -> list[tuple[str, str, str, str]]:
    """角图章名称区：两个非空栏位相同，或较短的一侧完整出现在另一侧里。"""
    present: list[tuple[str, str]] = []
    for name in fields:
        text = str(item.get(name) or "").strip()
        if text:
            present.append((name, text))
    found: list[tuple[str, str, str, str]] = []
    for index, (left, left_value) in enumerate(present):
        left_key = norm_space(left_value)
        for right, right_value in present[index + 1 :]:
            right_key = norm_space(right_value)
            if not left_key or not right_key:
                continue
            shorter, longer = (left_key, right_key) if len(left_key) <= len(right_key) else (right_key, left_key)
            if len(shorter) < min_len:
                continue
            if shorter == longer or shorter in longer:
                found.append((left, right, left_value, right_value))
    return found


def _group_key(drawing_no: str) -> str:
    parts = (drawing_no or "").upper().split("-")
    return "-".join(parts[:4]) if len(parts) >= 4 else drawing_no.upper()


def _suffix_num(drawing_no: str) -> int | None:
    parts = (drawing_no or "").split("-")
    if len(parts) >= 5 and parts[-1].isdigit():
        return int(parts[-1])
    return None


def norm_space(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def norm_field(name: str, value: Any) -> str:
    if name in {"revision"}:
        text = norm_space(value).replace("版次", "")
        if text.endswith("版"):
            text = text[:-1]
        return text.upper()
    if name == "page_count" and value in (None, "", 0, "0"):
        return ""
    if name in {"sheet_count", "page_count"}:
        matched = re.search(r"\d+", str(value or ""))
        return str(int(matched.group(0))) if matched else ""
    if name == "date":
        matched = re.search(r"(20\d{2})\D*(\d{1,2})\D*(\d{1,2})", norm_space(value))
        if not matched:
            return norm_space(value)
        return f"{int(matched.group(1)):04d}.{int(matched.group(2)):02d}.{int(matched.group(3)):02d}"
    if name in {"file_no", "drawing_no", "project_no"}:
        text = norm_space(value).upper().replace("—", "-").replace("－", "-")
        # 图框里的字母 O 常被识成数字 0，例如 OP 被识成 0P。只改「0 后面全是字母」的那一段。
        parts = []
        for index, part in enumerate(text.split("-")):
            # 图框首段的 BD 常被识成 B0，例如 BD25151 被识成 B025151。
            if index == 0 and re.fullmatch(r"B0\d+", part):
                part = "BD" + part[2:]
            # 字母 O 常被识成数字 0，例如 OP 被识成 0P。只改「0 后面全是字母」的那一段。
            if re.fullmatch(r"0[A-Z]+", part):
                part = "O" + part[1:]
            parts.append(part)
        return "-".join(parts)
    return norm_space(value)


def same_value(field: str, expected: str, actual: str) -> bool:
    if expected == actual:
        return True
    if field == "project_name" and expected and actual and (expected in actual or actual in expected):
        short, long = sorted((expected, actual), key=len)
        return len(short) / len(long) >= 0.8
    return False


def _show(value: Any) -> str:
    return norm_space(value) and str(value).strip() or "空"


def _as_float(value: Any) -> float | None:
    text = norm_space(value).replace("，", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _fmt_num(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def catalog_align(
    *,
    rows: list[dict[str, Any]],
    items: list[dict[str, Any]],
    public: dict[str, Any],
    public_fields: list[str],
    public_labels: dict[str, str],
    row_fields: list[dict[str, Any]],
    paper_factors: dict[str, Any] | None = None,
    pair_by: list[str] | None = None,
    identity_field: str | None = "file_no",
    report_missing: bool = True,
    report_extra: bool = True,
) -> list[dict[str, Any]]:
    """按 Skill 的 pair_by 配对，再比 public_fields 和 row_fields。

    identity_field 有值时：不是靠这个字段配上的，两边都有值且不同，就报不一致。
    report_missing / report_extra 控制是否报「目录有文件夹无」「文件夹有目录无」。
    默认先文件号再名称，并核对文件号，与改 Skill 之前相同。
    """
    diffs: list[dict[str, Any]] = []
    used: set[int] = set()
    keys = [str(key) for key in (pair_by or ["file_no", "name"]) if str(key).strip()]
    if not keys:
        keys = ["file_no", "name"]
    identity = "" if identity_field is None else str(identity_field).strip()

    def field_value(obj: dict[str, Any], field: str) -> str:
        if field == "name":
            return norm_field("name", obj.get("name"))
        return norm_field(field, obj.get(field))

    first = keys[0]
    by_first: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        key = field_value(item, first)
        if key:
            by_first.setdefault(key, []).append(item)

    paired: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    pending: list[dict[str, Any]] = []
    for row in rows:
        key = field_value(row, first)
        found = next((it for it in by_first.get(key, []) if id(it) not in used), None) if key else None
        if found is not None:
            used.add(id(found))
            paired.append((row, found, first))
        else:
            pending.append(row)

    for later in keys[1:]:
        still: list[dict[str, Any]] = []
        for row in pending:
            key = field_value(row, later)
            founds = [it for it in items if id(it) not in used and key and field_value(it, later) == key]
            if len(founds) == 1:
                used.add(id(founds[0]))
                paired.append((row, founds[0], later))
            else:
                still.append(row)
        pending = still

    for row in pending:
        if not report_missing:
            continue
        label = row.get("file_no") or row.get("name") or ""
        diffs.append(
            {
                "type": "missing_file",
                "severity": "high",
                "drawing_no": str(row.get("file_no") or ""),
                "desc": f"目录有该文件，文件夹中没有对应文件：{label} {row.get('name') or ''}".strip(),
                "suggestion": "补交该文件，或从目录中删除该条",
            }
        )

    for item in items:
        if id(item) in used or item.get("is_catalog"):
            continue
        if not report_extra:
            continue
        label = item.get("file_no") or item.get("name") or item.get("file") or ""
        diffs.append(
            {
                "type": "extra_file",
                "severity": "high",
                "drawing_no": str(item.get("file_no") or ""),
                "desc": f"文件夹中有该文件，目录没有对应条目：{label}",
                "suggestion": "把该文件补进目录，或从文件夹中移除",
            }
        )

    for row, item, via in paired:
        drawing_no = str(row.get("file_no") or item.get("file_no") or "")
        shown = item.get("file") or item.get("name") or drawing_no
        if identity and via != identity:
            expected_id = field_value(row, identity)
            actual_id = field_value(item, identity)
            if expected_id and actual_id and expected_id != actual_id:
                label = public_labels.get(identity, "文件号" if identity == "file_no" else identity)
                diffs.append(
                    {
                        "type": "file_no_mismatch" if identity == "file_no" else f"{identity}_mismatch",
                        "severity": "high",
                        "drawing_no": drawing_no,
                        "desc": f"{shown} {label}与目录不一致：目录「{row.get(identity)}」，文件「{item.get(identity)}」",
                        "suggestion": f"按目录修改该文件的{label}",
                    }
                )
        if not item.get("is_catalog"):
            for field in public_fields:
                expected = norm_field(field, public.get(field))
                actual = norm_field(field, item.get(field))
                label = public_labels.get(field, field)
                if not expected:
                    continue
                if not actual:
                    diffs.append(
                        {
                            "type": "missing_field",
                            "severity": "medium",
                            "drawing_no": drawing_no,
                            "desc": f"{shown} 未抽取到{label}，无法与目录核对",
                            "suggestion": f"检查页眉或图框中的{label}",
                        }
                    )
                    continue
                if not same_value(field, expected, actual):
                    diffs.append(
                        {
                            "type": "public_mismatch",
                            "severity": "high",
                            "drawing_no": drawing_no,
                            "desc": f"{shown} {label}与目录不一致：目录「{_show(public.get(field))}」，文件「{_show(item.get(field))}」",
                            "suggestion": f"将{label}改成与目录页眉一致",
                        }
                    )
        for pair in row_fields:
            row_key = pair.get("row") or ""
            item_key = pair.get("item") or row_key
            expected = norm_field(item_key if item_key in {"sheet_count", "page_count", "revision", "date", "stage"} else row_key, row.get(row_key))
            if item_key == "page_count":
                expected = norm_field("page_count", row.get(row_key))
            actual = norm_field(item_key, item.get(item_key))
            label = pair.get("label") or item_key
            when_empty = pair.get("when_empty") or "issue"
            if not expected:
                continue
            if not actual:
                if when_empty == "skip":
                    continue
                diffs.append(
                    {
                        "type": pair.get("type") or "missing_field",
                        "severity": "medium",
                        "drawing_no": drawing_no,
                        "desc": f"{shown} 未抽取到{label}，目录要求「{_show(row.get(row_key))}」",
                        "suggestion": f"在页眉或图框中补上{label}",
                    }
                )
                continue
            if expected != actual:
                diffs.append(
                    {
                        "type": pair.get("type") or "mismatch",
                        "severity": "high",
                        "drawing_no": drawing_no,
                        "desc": f"{shown} {label}与目录不一致：目录「{_show(row.get(row_key))}」，文件「{_show(item.get(item_key))}」",
                        "suggestion": f"按目录修改该文件的{label}",
                    }
                )
        diffs.extend(_equivalent_diffs(row, item, shown, drawing_no, paper_factors or {}))
    return diffs


def _equivalent_diffs(
    row: dict[str, Any],
    item: dict[str, Any],
    shown: str,
    drawing_no: str,
    paper_factors: dict[str, Any],
) -> list[dict[str, Any]]:
    """折合1#图纸 = 目录自然张数 × 图幅系数。图幅由文件页面尺寸判定。"""
    if not paper_factors or _as_float(row.get("equivalent")) is None:
        return []
    sheets = _as_float(row.get("sheet_count"))
    listed = _as_float(row.get("equivalent"))
    if sheets is None or listed is None:
        return []
    size = str(item.get("paper_size") or "")
    width = item.get("paper_width_mm")
    height = item.get("paper_height_mm")
    if not size and width in (None, "") and height in (None, ""):
        return []
    factor = _as_float(paper_factors.get(size))
    if factor is None:
        measured = f"{width}×{height} mm" if width not in (None, "") else "未知尺寸"
        known = "、".join(str(name) for name in paper_factors)
        return [
            {
                "type": "equivalent_mismatch",
                "severity": "medium",
                "drawing_no": drawing_no,
                "desc": f"{shown} 页面尺寸 {measured}，不是{known}，无法核算折合1#图纸",
                "suggestion": "确认图幅后再核折合1#图纸",
            }
        ]
    calculated = round(sheets * factor, 3)
    if abs(calculated - round(listed, 3)) <= 0.001:
        return []
    return [
        {
            "type": "equivalent_mismatch",
            "severity": "high",
            "drawing_no": drawing_no,
            "desc": f"{shown} 折合1#图纸与计算不符：目录「{_show(row.get('equivalent'))}」，图幅 {size}、自然张数 {_fmt_num(sheets)}，应为 {_fmt_num(calculated)}",
            "suggestion": "按自然张数乘以图幅系数修改目录中的折合1#图纸",
        }
    ]


JudgeFn = Callable[..., dict[str, Any]]


def _judge_default(**kwargs: Any) -> dict[str, Any]:
    from ai.agents.extract_info import judge_json

    return judge_json(**kwargs)


def _whitelist_for(glossary: dict[str, Any] | None, discipline: str) -> list[str]:
    """common + 本专业；专业未知时合并全部，宁可少报。"""
    if not isinstance(glossary, dict):
        return []
    words: list[str] = []
    buckets = [glossary.get("common")]
    if discipline and discipline in glossary:
        buckets.append(glossary.get(discipline))
    else:
        buckets.extend(v for k, v in glossary.items() if k != "common")
    for bucket in buckets:
        if isinstance(bucket, list):
            words.extend(str(w).strip() for w in bucket if str(w).strip())
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def _confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number > 1.0:
        number = number / 100.0 if number <= 100 else 1.0
    return max(0.0, min(1.0, number))


def llm_judge(
    *,
    files: list[dict[str, Any]] | None,
    prompt_id: str,
    glossary: dict[str, Any] | None = None,
    min_confidence: float = 0.7,
    kinds: list[str] | None = None,
    judge_fn: JudgeFn | None = None,
) -> list[dict[str, Any]]:
    """语义类判定（错别字）。只负责组织输入、调用判定、过滤阈值，不写具体文案。

    files 是 notes.files；每份文件的全部说明行一次送判，不逐行调。
    返回结构化差异：{type: typo, file, drawing_no, page, line, no, kind, text, wrong, correct, reason, confidence, bbox}
    或 {type: tool_error, file, drawing_no, desc}。judge_fn 可注入，便于离线回归。
    """
    judge = judge_fn or _judge_default
    allowed = {str(k) for k in (kinds or []) if str(k).strip()}
    diffs: list[dict[str, Any]] = []
    for book in files or []:
        if not isinstance(book, dict):
            continue
        file_name = str(book.get("file") or "")
        drawing_no = str(book.get("drawing_no") or "")
        discipline = str(book.get("discipline") or "")
        # 行号跨说明块连续编号，模型回的 line 能唯一定位到行。
        index: dict[int, tuple[dict[str, Any], dict[str, Any]]] = {}
        rendered: list[str] = []
        number = 0
        for item in book.get("items") or []:
            if not isinstance(item, dict):
                continue
            for line in item.get("lines") or []:
                if not isinstance(line, dict):
                    continue
                kind = str(line.get("kind") or "条文")
                if allowed and kind not in allowed:
                    continue
                text = str(line.get("text") or "").strip()
                if not text:
                    continue
                number += 1
                index[number] = (item, line)
                rendered.append(f"{number}. [{kind}] {text}")
        if not rendered:
            continue
        whitelist = _whitelist_for(glossary, discipline)
        data = judge(
            prompt_id=prompt_id,
            whitelist="、".join(whitelist) if whitelist else "（无）",
            lines="\n".join(rendered),
        )
        if data.get("_error"):
            diffs.append({"type": "tool_error", "file": file_name, "drawing_no": drawing_no, "desc": str(data["_error"])})
            continue
        items = data.get("items")
        if not isinstance(items, list):
            continue
        for found in items:
            if not isinstance(found, dict):
                continue
            wrong = str(found.get("wrong") or "").strip()
            correct = str(found.get("correct") or "").strip()
            if not wrong or wrong == correct:
                continue
            if whitelist and any(wrong in w or w in wrong for w in whitelist):
                continue
            confidence = _confidence(found.get("confidence"))
            if confidence < float(min_confidence or 0):
                continue
            try:
                line_no = int(found.get("line"))
            except (TypeError, ValueError):
                line_no = 0
            item, line = index.get(line_no, ({}, {}))
            text = str(line.get("text") or "")
            if text and wrong not in text:
                # 模型报的字不在该行原文里，多半是行号对错或已自行改写，降级不报。
                continue
            diffs.append(
                {
                    "type": "typo",
                    "file": file_name,
                    "drawing_no": drawing_no,
                    "page": item.get("page"),
                    "line": line_no,
                    "no": str(line.get("no") or "") or str(line_no),
                    "kind": str(line.get("kind") or ""),
                    "text": text,
                    "wrong": wrong,
                    "correct": correct,
                    "reason": str(found.get("reason") or ""),
                    "confidence": round(confidence, 3),
                    "bbox": item.get("bbox"),
                }
            )
    return diffs


def expect(actual: Any, expected: Any) -> bool:
    """通用期望值比对：actual 是否等于 expected（去空白、忽略大小写）。

    只做比对，不读文件、不调模型、不硬编码业务值；expected 由审查规则传入。
    """
    return norm_space(actual).upper() == norm_space(expected).upper()


def seq_groups(drawing_nos: list[str]) -> list[tuple[str, list[int]]]:
    groups: dict[str, list[int]] = {}
    for no in drawing_nos:
        n = _suffix_num(no)
        if n is None:
            continue
        groups.setdefault(_group_key(no), []).append(n)
    holes: list[tuple[str, list[int]]] = []
    for key, nums in groups.items():
        s = sorted(set(nums))
        expected = list(range(s[0], s[-1] + 1)) if s else []
        missing = [x for x in expected if x not in s]
        if missing:
            holes.append((key, missing))
    return holes


def _last_int(text: str) -> tuple[int, int, int] | None:
    """最后一个数字串的 (值, 起始下标, 结束下标)。没有数字返回 None。"""
    found = None
    for matched in re.finditer(r"\d+", text or ""):
        found = matched
    if found is None:
        return None
    return int(found.group(0)), found.start(), found.end()


def _digit_width(raw: Any) -> int:
    """最后一个数字串的位数，用来还原补零写法（002 → 3）。"""
    parts = re.findall(r"\d+", norm_space(raw))
    return len(parts[-1]) if parts else 1


def _clean_prefix(text: str) -> str:
    """前缀去掉尾部的分隔符与序数词，仅用于文案展示与分组。"""
    return re.sub(r"[\s\-_/.第]+$", "", text)


def parse_sheet_no(raw: Any, separators: list[str] | None = None) -> tuple[str, int | None]:
    """把页号原文拆成 (前缀, 序号)。只做拆分，业务规则由审查规则传入。

    审查规则没配 separators 时走默认规则：取最右侧的数字串（001 → 1、BD-…-002 → 2、第3页 → 3），
    不做任何分隔符推断。配了 separators 才启用：斜杠写法（3/8 取左侧页号）→ 分隔符写法
    （最后一个「后面是纯数字」的分隔符）→ 兜底最右数字串。拆不出序号返回 ("", None)。
    """
    text = norm_space(raw)
    if not text:
        return "", None
    seps = [str(s) for s in (separators or []) if str(s)]

    if not seps:
        found = _last_int(text)
        if found is None:
            return "", None
        value, start, _ = found
        return _clean_prefix(text[:start]), value

    if "/" in seps and "/" in text:
        left = text.split("/", 1)[0]
        found = _last_int(left)
        if found is not None:
            return _clean_prefix(left[: found[1]]), found[0]

    cut, cut_len = -1, 0
    for sep in seps:
        if sep == "/":
            continue
        index = text.rfind(sep)
        if index < 0:
            continue
        tail = text[index + len(sep) :]
        if tail.isdigit() and index > cut:
            cut, cut_len = index, len(sep)
    if cut >= 0:
        return _clean_prefix(text[:cut]), int(text[cut + cut_len :])

    found = _last_int(text)
    if found is None:
        return "", None
    value, start, _ = found
    return _clean_prefix(text[:start]), value


_SHAPE_LABEL = {
    "plain": "纯数字",
    "dash": "短横线",
    "under": "下划线",
    "slash": "斜杠",
    "cn": "中文第X页",
    "mixed": "混合",
    "empty": "空页号",
}


def _style_key(raw: Any) -> str:
    """编号形态。只看「长什么样」，不看具体前缀，用于把同一套编号规则归到一组。"""
    text = norm_space(raw)
    if not text:
        return "empty"
    if "第" in text and "页" in text:
        return "cn"
    if "/" in text:
        return "slash"
    if "_" in text:
        return "under"
    if "-" in text:
        return "dash"
    if not re.search(r"[A-Za-z\u4e00-\u9fff]", text):
        return "plain"
    return "mixed"


def _shape_of(key: str) -> str:
    """组的显示名：形态分组给中文名，前缀分组就给前缀本身。"""
    return _SHAPE_LABEL.get(key, key)


def seq_audit(
    *,
    items: list[dict[str, Any]] | None,
    field: str,
    separators: list[str] | None = None,
    group_by: str = "shape",
    start_page: int = 1,
    step: int = 1,
    parity: str = "any",
    total_field: str = "",
    actual_total: Any = None,
) -> list[dict[str, Any]]:
    """分组后查缺号、跳号、重复、总页数不符。

    只返回结构化差异，文案由审查规则决定：{type, severity, prefix, missing, value, ...}。
    group_by：shape=按编号形态分组（默认，一个 PDF 里多套编号规则各成一组）；
    prefix=按前缀字面值分组；all=不分组。
    start_page：PDF 物理页起点，前面的页不纳入审查；总页数核对按剩余页数算。
    step=1 查 1,2,3…；step=2 查 1,3,5… 或 2,4,6…（组内最小值定起点）。
    """
    diffs: list[dict[str, Any]] = []
    step = max(1, int(step or 1))
    start_page = max(1, int(start_page or 1))
    if group_by not in {"shape", "prefix", "all"}:
        group_by = "shape"
    groups: dict[str, list[tuple[int, Any]]] = {}
    widths: dict[str, list[int]] = {}
    prefixes: dict[str, set[str]] = {}
    order: list[str] = []
    declared: dict[int, list[Any]] = {}

    for item in items or []:
        if not isinstance(item, dict):
            continue
        page = item.get("page")
        # 封面、说明页等起点前的页面不参与编号审查。
        if isinstance(page, int) and page < start_page:
            continue
        raw = item.get(field)
        if total_field:
            raw_total = norm_space(item.get(total_field))
            found_total = re.search(r"\d+", raw_total) if raw_total else None
            if found_total:
                declared.setdefault(int(found_total.group(0)), []).append(page)
        prefix, num = parse_sheet_no(raw, separators)
        if num is None:
            diffs.append(
                {
                    "type": "unparseable",
                    "severity": "medium",
                    "page": page,
                    "prefix": prefix,
                    "desc": f"第 {page} 页未能抽出页号",
                    "suggestion": "",
                }
            )
            continue
        key = "" if group_by == "all" else (prefix if group_by == "prefix" else _style_key(raw))
        if key not in groups:
            groups[key] = []
            widths[key] = []
            prefixes[key] = set()
            order.append(key)
        groups[key].append((num, page))
        widths[key].append(_digit_width(raw))
        prefixes[key].add(prefix)

    for key in order:
        start = len(diffs)
        entries = groups[key]
        width = max(widths[key]) if widths[key] else 1
        # 形态分组时组内前缀往往不同，不一致就不前缀进文案，避免误导。
        prefix = next(iter(prefixes[key])) if len(prefixes[key]) == 1 else ""
        counts: dict[int, list[Any]] = {}
        for num, page in entries:
            counts.setdefault(num, []).append(page)

        for num in sorted(counts):
            pages = counts[num]
            if len(pages) <= 1:
                continue
            shown = f"{num:0{width}d}"
            diffs.append(
                {
                    "type": "duplicate",
                    "severity": "high",
                    "prefix": prefix,
                    "value": shown,
                    "count": len(pages),
                    "pages": "、".join(str(p) for p in pages),
                    "desc": f"{prefix}{shown} 页号重复，出现在第 {'、'.join(str(p) for p in pages)} 页",
                    "suggestion": "",
                }
            )

        uniq = sorted(counts)
        present = set(uniq)
        expected = list(range(uniq[0], uniq[-1] + 1, step))
        ladder = set(expected)
        missing = [x for x in expected if x not in present]
        if missing:
            shown = "、".join(f"{x:0{width}d}" for x in missing)
            diffs.append(
                {
                    "type": "gap",
                    "severity": "high",
                    "prefix": prefix,
                    "missing": shown,
                    "first": uniq[0],
                    "last": uniq[-1],
                    "step": step,
                    "desc": f"{prefix}页号不连续，缺 {shown}",
                    "suggestion": "",
                }
            )
        # step>1 时，落在间隔规律之外的号也要报（如要求 1,3,5 却出现 2、4）。step=1 时恒为空。
        off = [x for x in uniq if x not in ladder]
        if off:
            shown = "、".join(f"{x:0{width}d}" for x in off)
            diffs.append(
                {
                    "type": "off_ladder",
                    "severity": "high",
                    "prefix": prefix,
                    "value": shown,
                    "step": step,
                    "desc": f"{prefix}页号 {shown} 不符合 {step} 号间隔的编排",
                    "suggestion": "",
                }
            )

        if parity in {"odd", "even"}:
            want_odd = parity == "odd"
            if (uniq[0] % 2 == 1) != want_odd:
                shown = f"{uniq[0]:0{width}d}"
                diffs.append(
                    {
                        "type": "parity",
                        "severity": "medium",
                        "prefix": prefix,
                        "value": shown,
                        "desc": f"{prefix}起始页号 {shown} 不符合{'奇' if want_odd else '偶'}数要求",
                        "suggestion": "",
                    }
                )

        # 把组标识带进差异，多组时文案能区分是哪一套编号。
        for diff in diffs[start:]:
            diff["group"] = key
            diff["group_label"] = _shape_of(key)

    if declared:
        values = sorted(declared)
        actual: int | None = None
        if actual_total not in (None, "", 0, "0"):
            try:
                # 起点前的封面页不参与编号，总页数核对按剩余页数算。
                actual = int(actual_total) - (start_page - 1)
            except (TypeError, ValueError):
                actual = None
        if len(values) > 1:
            diffs.append(
                {
                    "type": "total_mismatch",
                    "severity": "medium",
                    "declared": str(values[0]),
                    "actual": str(actual if actual is not None else values[-1]),
                    "desc": f"各页标注的总页数不一致：{'、'.join(str(v) for v in values)}",
                    "suggestion": "",
                }
            )
        elif actual is not None and values[0] != actual:
            diffs.append(
                {
                    "type": "total_mismatch",
                    "severity": "medium",
                    "declared": str(values[0]),
                    "actual": str(actual),
                    "desc": f"总页数不符：标注 {values[0]}，实际 {actual} 页",
                    "suggestion": "",
                }
            )
    return diffs
