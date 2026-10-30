"""运行配置。服务地址、图框模型和 DPI 都可被环境变量覆盖。"""

from __future__ import annotations

import os
from pathlib import Path

FRAME_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = FRAME_ROOT.parent
WORK_ROOT = FRAME_ROOT / "data" / "work"


def _load_dotenv() -> None:
    """把仓库根目录的 .env 填进 os.environ。已有环境变量不覆盖，密钥不进代码。"""
    path = FRAME_ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


_load_dotenv()

# 前端「图像预处理预览」的结果图目录，同时作为 /static/previews 的挂载目录。
PREVIEW_DIR = WORK_ROOT / "preprocess_preview"

# 大模型走 OpenAI 兼容接口。本地 vLLM（192.168.31.9:8000）或阿里云百炼均可，用 .env 切换。
# 百炼示例：VLM_BASE_URL=.../compatible-mode/v1  VLM_MODEL=qwen3.8-27b  VLM_API_KEY=sk-...
VLM_BASE_URL = os.getenv("VLM_BASE_URL", "http://192.168.31.9:8000/v1")
VLM_MODEL = os.getenv("VLM_MODEL", "/data/models")
VLM_API_KEY = os.getenv("VLM_API_KEY", "EMPTY")

# 关闭「深度思考」的参数写法随服务商不同：
#   vllm      → extra_body={"chat_template_kwargs": {"enable_thinking": False}}
#   dashscope → extra_body={"enable_thinking": False}（阿里云百炼 compatible-mode）
# 不设 VLM_PROVIDER 时按 base_url 推断。
def _provider() -> str:
    explicit = os.getenv("VLM_PROVIDER", "").strip().lower()
    if explicit:
        return explicit
    return "dashscope" if "aliyuncs.com" in VLM_BASE_URL else "vllm"


VLM_PROVIDER = _provider()
VLM_EXTRA_BODY: dict = (
    {"enable_thinking": False} if VLM_PROVIDER == "dashscope" else {"chat_template_kwargs": {"enable_thinking": False}}
)
VLM_TIMEOUT = int(os.getenv("VLM_TIMEOUT", "180"))

PDF_DPI = int(os.getenv("PDF_DPI", "300"))

def _weights_path() -> Path:
    raw = os.getenv("YOLO_WEIGHTS", str(REPO_ROOT / "best.pt"))
    path = Path(raw)
    if path.is_file():
        return path
    beside = (FRAME_ROOT / path).resolve()
    return beside if beside.is_file() else path


YOLO_WEIGHTS = _weights_path()
YOLO_IMGSZ = int(os.getenv("YOLO_IMGSZ", "1280"))
YOLO_CONF = float(os.getenv("YOLO_CONF", "0.5"))

# 版面权重（runs/cq_layout/best.pt，类别 图框/表格/说明，训练 imgsz=1536）。
# 与图框权重分开配置，说明栏链路只读这一组，不影响既有 title_block 路径。
# 未单独指定时退回 YOLO_WEIGHTS，便于只放一个 best.pt 的环境。
YOLO_WEIGHTS_LAYOUT = Path(os.getenv("YOLO_WEIGHTS_LAYOUT", str(YOLO_WEIGHTS)))
YOLO_IMGSZ_LAYOUT = int(os.getenv("YOLO_IMGSZ_LAYOUT", "1536"))
# 说明栏漏检代价高于多裁，阈值放低；多裁出的块抄不出文字自然为空。
YOLO_CONF_NOTES = float(os.getenv("YOLO_CONF_NOTES", "0.3"))

# 远程推理：权重留在 GPU 服务器，本机只上传图片、收回框坐标。密码只放 .env。
YOLO_REMOTE_HOST = os.getenv("YOLO_REMOTE_HOST", "").strip()
YOLO_REMOTE_PORT = int(os.getenv("YOLO_REMOTE_PORT", "22"))
YOLO_REMOTE_USER = os.getenv("YOLO_REMOTE_USER", "").strip()
YOLO_REMOTE_PASSWORD = os.getenv("YOLO_REMOTE_PASSWORD", "")
YOLO_REMOTE_WEIGHTS = os.getenv(
    "YOLO_REMOTE_WEIGHTS",
    "/data/zzx/图纸处理/runs/cq_layout/weights/best.pt",
).strip()
# 登录 shell 没有 conda；这台机器的 ultralytics 在这个解释器里。
YOLO_REMOTE_PYTHON = os.getenv("YOLO_REMOTE_PYTHON", "/data/andaconda/conda/bin/python").strip()

# 审查点里的类别名 → 权重里的类别名。
# 旧图框权重类别为 title_block；版面权重类别为中文名，两套权重按 CATEGORY 分别映射。
CATEGORY_TO_CLASS = {
    "图框": "title_block",
    "标题栏": "title_block",
    "title_block": "title_block",
    "说明栏": "说明",
    "说明": "说明",
    "表格": "表格",
}

# 说明栏检测来源：yolo（默认）| label_json（开发态：读与 PNG 同名的 X-AnyLabeling 标注）。
NOTES_DETECT_SOURCE = os.getenv("NOTES_DETECT_SOURCE", "yolo").strip().lower()
# 说明栏裁图送 VLM 时允许的最长边；默认 2048 会把 3.5mm 字高压到难以辨认。
NOTES_VLM_MAX_SIDE = int(os.getenv("NOTES_VLM_MAX_SIDE", "3000"))
# 说明栏裁图高于此值时纵向切条送模型，重叠按比例保留。
NOTES_STRIP_HEIGHT = int(os.getenv("NOTES_STRIP_HEIGHT", "1800"))
NOTES_STRIP_OVERLAP = float(os.getenv("NOTES_STRIP_OVERLAP", "0.1"))
