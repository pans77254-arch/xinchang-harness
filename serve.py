"""Web 服务启停：python serve.py start | stop | status | restart"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Set

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
PID_FILE = LOG_DIR / "web.pid"
LOG_FILE = LOG_DIR / "web.log"
DEFAULT_PORT = int(os.getenv("WEB_PORT", "8765"))
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200


def _port() -> int:
    return int(os.getenv("WEB_PORT", str(DEFAULT_PORT)))


def _pid_listening(port: int) -> Optional[int]:
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(
                ["netstat", "-ano"],
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None
        needle = f":{port}"
        for line in out.splitlines():
            if needle not in line or "LISTENING" not in line.upper():
                continue
            parts = line.split()
            if not parts:
                continue
            try:
                return int(parts[-1])
            except ValueError:
                continue
        return None

    try:
        out = subprocess.check_output(["ss", "-tlnp"], text=True, errors="ignore")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    for line in out.splitlines():
        if f":{port}" in line and "pid=" in line:
            after = line.split("pid=", 1)[1]
            num = "".join(ch for ch in after if ch.isdigit())
            if num:
                return int(num)
    return None


def _is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}"],
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _kill(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def _read_pidfile() -> Optional[int]:
    if not PID_FILE.is_file():
        return None
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def _write_pidfile(pid: int) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(pid), encoding="utf-8")


def _tail_log(n: int = 30) -> str:
    if not LOG_FILE.is_file():
        return "(尚无日志)"
    lines = LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
    return "\n".join(lines[-n:]) if lines else "(日志为空)"


def cmd_stop() -> int:
    port = _port()
    pids: Set[int] = set()
    saved = _read_pidfile()
    if saved:
        pids.add(saved)
    listening = _pid_listening(port)
    if listening:
        pids.add(listening)

    if not pids:
        if PID_FILE.exists():
            PID_FILE.unlink()
        print(f"已停止（端口 {port} 当前没有服务）。")
        return 0

    for pid in pids:
        if _is_alive(pid):
            print(f"正在停止 PID {pid} ...")
            _kill(pid)

    time.sleep(0.5)
    if PID_FILE.exists():
        PID_FILE.unlink()
    print(f"已停止。地址原为 http://127.0.0.1:{port}")
    return 0


def cmd_status() -> int:
    port = _port()
    listening = _pid_listening(port)
    saved = _read_pidfile()
    if listening:
        print(f"运行中  PID={listening}")
        print(f"页面    http://127.0.0.1:{port}")
        return 0
    if saved and _is_alive(saved):
        print(f"进程还在 PID={saved}，但端口 {port} 未监听。")
        print("日志：")
        print(_tail_log())
        return 1
    print(f"未运行（端口 {port}）。启动: python serve.py start")
    return 1


def cmd_start() -> int:
    port = _port()
    url = f"http://127.0.0.1:{port}"
    print(f"目标地址  {url}", flush=True)

    existing = _pid_listening(port)
    if existing:
        print(f"已在运行  PID={existing}")
        print(f"请浏览器打开  {url}")
        return 0

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_fp = open(LOG_FILE, "a", encoding="utf-8")
    log_fp.write(f"\n----- start {time.strftime('%Y-%m-%d %H:%M:%S')} -----\n")
    log_fp.flush()

    env = os.environ.copy()
    env.setdefault("WEB_PORT", str(port))
    # Windows：不要用 DETACHED_PROCESS（不能和重定向日志一起用，子进程会立刻退出）
    flags = 0
    if sys.platform == "win32":
        flags = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP

    cmd = [sys.executable, "-u", str(ROOT / "web.py")]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            env=env,
            stdout=log_fp,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=flags,
            start_new_session=(sys.platform != "win32"),
        )
    except OSError as exc:
        print(f"启动失败: {exc}")
        return 1

    _write_pidfile(proc.pid)
    print(f"已拉起进程 PID={proc.pid}，等待端口监听...", flush=True)

    deadline = time.time() + 12
    while time.time() < deadline:
        code = proc.poll()
        if code is not None:
            print(f"进程已退出，退出码={code}。日志末尾：")
            print(_tail_log())
            if PID_FILE.exists():
                PID_FILE.unlink()
            return 1
        if _pid_listening(port):
            print(f"已启动")
            print(f"请打开  {url}")
            print(f"日志    {LOG_FILE}")
            return 0
        time.sleep(0.3)

    print("12 秒内端口仍未监听。日志末尾：")
    print(_tail_log())
    print(f"仍可尝试打开  {url}")
    return 1


def cmd_restart() -> int:
    cmd_stop()
    time.sleep(0.5)
    return cmd_start()


def main() -> int:
    print(f"[serve] python={sys.executable} version={sys.version.split()[0]}", flush=True)
    parser = argparse.ArgumentParser(description="信创版 Harness Web 启停")
    parser.add_argument("action", choices=["start", "stop", "status", "restart"])
    args = parser.parse_args()
    if args.action == "start":
        return cmd_start()
    if args.action == "stop":
        return cmd_stop()
    if args.action == "status":
        return cmd_status()
    return cmd_restart()


if __name__ == "__main__":
    raise SystemExit(main())
