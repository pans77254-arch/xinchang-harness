"""在 GPU 服务器上跑版面 YOLO，本机只拿框。

一次 SSH 拉起常驻进程，模型只加载一次。每张图 SFTP 上传后写一行请求，读一行 JSON 框。
框坐标是原图像素，调用方在本地裁剪，不把裁图传回来。
"""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any

from ai.config import (
    YOLO_CONF_NOTES,
    YOLO_IMGSZ_LAYOUT,
    YOLO_REMOTE_HOST,
    YOLO_REMOTE_PASSWORD,
    YOLO_REMOTE_PORT,
    YOLO_REMOTE_USER,
    YOLO_REMOTE_PYTHON,
    YOLO_REMOTE_WEIGHTS,
)

_REMOTE_DIR = "/tmp/cq_notes_yolo"
_WORKER = r"""
import json, sys
from ultralytics import YOLO

cfg = json.loads(sys.stdin.readline())
try:
    model = YOLO(cfg["weights"])
except Exception as exc:
    sys.stdout.write(json.dumps({"ready": False, "error": str(exc)}, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    raise SystemExit(1)
names = {int(k): str(v) for k, v in model.names.items()}
wanted = cfg.get("class_name") or ""
ids = None
if wanted:
    if wanted not in names.values():
        sys.stdout.write(json.dumps({
            "ready": False,
            "error": "权重中没有类别 %s，现有：%s" % (wanted, "、".join(names.values())),
        }, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        raise SystemExit(1)
    ids = {idx for idx, name in names.items() if name == wanted}
sys.stdout.write(json.dumps({"ready": True, "names": list(names.values())}, ensure_ascii=False) + "\n")
sys.stdout.flush()
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    try:
        result = model.predict(source=req["image"], imgsz=int(req["imgsz"]), conf=float(req["conf"]), verbose=False)[0]
        boxes = []
        if result.boxes is not None:
            for box in result.boxes:
                cls_id = int(box.cls[0])
                if ids is not None and cls_id not in ids:
                    continue
                boxes.append({
                    "bbox": [round(float(v), 1) for v in box.xyxy[0].tolist()],
                    "confidence": round(float(box.conf[0]), 4),
                    "class_name": names.get(cls_id, ""),
                })
        boxes.sort(key=lambda item: -item["confidence"])
        payload = {"ok": True, "boxes": boxes}
    except Exception as exc:
        payload = {"ok": False, "error": str(exc), "boxes": []}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()
"""

_session: "_RemoteYolo | None" = None


def _read_line(stdout, timeout: float) -> str:
    channel = stdout.channel
    channel.settimeout(timeout)
    raw = stdout.readline()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    return (raw or "").strip()


class _RemoteYolo:
    def __init__(self) -> None:
        import paramiko

        if not YOLO_REMOTE_HOST or not YOLO_REMOTE_USER:
            raise RuntimeError("未配置 YOLO_REMOTE_HOST / YOLO_REMOTE_USER")
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(
            YOLO_REMOTE_HOST,
            port=YOLO_REMOTE_PORT,
            username=YOLO_REMOTE_USER,
            password=YOLO_REMOTE_PASSWORD,
            timeout=30,
            banner_timeout=90,
            auth_timeout=60,
        )
        self.sftp = self.client.open_sftp()
        self._mkdirs()
        with self.sftp.file(f"{_REMOTE_DIR}/worker.py", "w") as handle:
            handle.write(_WORKER)
        cmd = f"{YOLO_REMOTE_PYTHON} -u {_REMOTE_DIR}/worker.py"
        self.stdin, self.stdout, self.stderr = self.client.exec_command(cmd, get_pty=False)
        self.stderr_lines: list[str] = []
        threading.Thread(target=self._drain_stderr, daemon=True).start()
        self.stdin.write(
            json.dumps({"weights": YOLO_REMOTE_WEIGHTS, "class_name": ""}, ensure_ascii=False)
            + "\n"
        )
        self.stdin.flush()
        ready = _read_line(self.stdout, 180)
        if not ready:
            tail = "".join(self.stderr_lines)[-500:]
            raise RuntimeError(f"远程 YOLO 没有就绪。{tail}")
        payload = json.loads(ready)
        if not payload.get("ready"):
            raise RuntimeError(payload.get("error") or "远程 YOLO 加载失败")

    def _drain_stderr(self) -> None:
        try:
            for raw in iter(self.stderr.readline, ""):
                text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
                if text:
                    self.stderr_lines.append(text)
                    self.stderr_lines = self.stderr_lines[-20:]
        except Exception:
            return

    def _mkdirs(self) -> None:
        for path in (_REMOTE_DIR, f"{_REMOTE_DIR}/in"):
            try:
                self.sftp.mkdir(path)
            except OSError:
                pass

    def predict(self, image_path: str | Path, *, imgsz: int, conf: float) -> list[dict[str, Any]]:
        src = Path(image_path)
        remote = f"{_REMOTE_DIR}/in/{uuid.uuid4().hex}{src.suffix.lower() or '.png'}"
        self.sftp.put(str(src), remote)
        try:
            self.stdin.write(json.dumps({"image": remote, "imgsz": imgsz, "conf": conf}) + "\n")
            self.stdin.flush()
            line = _read_line(self.stdout, 180)
        finally:
            try:
                self.sftp.remove(remote)
            except OSError:
                pass
        if not line:
            tail = "".join(self.stderr_lines)[-500:]
            raise RuntimeError(f"远程 YOLO 没有返回结果。{tail}")
        payload = json.loads(line)
        if not payload.get("ok"):
            raise RuntimeError(payload.get("error") or "远程推理失败")
        return list(payload.get("boxes") or [])

    def close(self) -> None:
        try:
            self.stdin.close()
        except Exception:
            pass
        try:
            self.client.close()
        except Exception:
            pass


def predict_remote(
    image_path: str | Path,
    *,
    imgsz: int = YOLO_IMGSZ_LAYOUT,
    conf: float = YOLO_CONF_NOTES,
) -> list[dict[str, Any]]:
    """返回 [{bbox, confidence, class_name}]，坐标是原图像素。class_name 为空时返回权重里的全部类别。"""
    global _session
    if _session is None:
        _session = _RemoteYolo()
    try:
        return _session.predict(image_path, imgsz=imgsz, conf=conf)
    except Exception:
        try:
            _session.close()
        except Exception:
            pass
        _session = None
        raise


def remote_enabled() -> bool:
    return bool(YOLO_REMOTE_HOST and YOLO_REMOTE_USER)
