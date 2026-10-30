"""启动 FastAPI。在仓库根目录执行：python scripts/run_api.py

端口可通过 --port 参数或环境变量 PORT 指定，默认 8000。
指定端口被占用时自动尝试下一个端口，并打印占用进程信息。
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn


def _port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def _find_owner(port: int) -> str:
    try:
        result = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=3)
        for line in result.stdout.splitlines():
            if f":{port} " in line or line.rstrip().endswith(f":{port}"):
                return line.strip()
    except Exception:
        pass
    return "（运行 ss -tlnp 查看占用进程）"


def main() -> None:
    parser = argparse.ArgumentParser(description="启动图纸审查 API 服务")
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    parser.add_argument("--no-auto-port", action="store_true", help="端口被占时不自动尝试下一个")
    args = parser.parse_args()

    host, port = args.host, args.port
    while True:
        if not _port_in_use(port, host):
            break
        owner = _find_owner(port)
        if args.no_auto_port:
            print(f"[ERROR] 端口 {port} 已被占用：{owner}", file=sys.stderr)
            sys.exit(1)
        print(f"[WARN] 端口 {port} 已被占用（{owner}），自动尝试 {port + 1}")
        port += 1
        if port > 65535:
            print("[ERROR] 没有可用端口", file=sys.stderr)
            sys.exit(1)

    print(f"启动审查服务：http://{host}:{port}")
    uvicorn.run("backend.app.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
