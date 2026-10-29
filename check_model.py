"""检查 Jetson / llama-server 是否可用（从 Windows 或本机运行）"""

from __future__ import annotations

import json
import os
import sys

import requests

DEFAULT_URL = os.getenv("LLAMA_SERVER_URL", "http://192.168.110.74:8080").rstrip("/")
DEFAULT_MODEL = os.getenv("LLAMA_MODEL", "local-model")


def try_get(url: str, timeout: int = 5) -> tuple[bool, str]:
    try:
        r = requests.get(url, timeout=timeout)
        body = r.text[:500]
        return r.ok, f"HTTP {r.status_code}\n{body}"
    except requests.RequestException as exc:
        return False, str(exc)


def try_post_chat(base: str, model: str) -> tuple[bool, str]:
    url = f"{base}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "只回复：ok"}],
        "max_tokens": 16,
        "temperature": 0,
    }
    try:
        r = requests.post(url, json=payload, timeout=120)
        if not r.ok:
            return False, f"HTTP {r.status_code}\n{r.text[:800]}"
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        return True, content
    except requests.RequestException as exc:
        return False, str(exc)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        return False, f"响应格式异常: {exc}\n{r.text[:800] if 'r' in dir() else ''}"


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL).rstrip("/")
    model = os.getenv("LLAMA_MODEL", DEFAULT_MODEL)

    print("=" * 60)
    print("信创 Harness · 模型连通性诊断")
    print("=" * 60)
    print(f"目标地址 : {base}")
    print(f"模型名称 : {model}")
    print(f"（可通过环境变量 LLAMA_SERVER_URL / LLAMA_MODEL 覆盖）")
    print()

    checks = [
        ("GET /health", f"{base}/health"),
        ("GET /v1/models", f"{base}/v1/models"),
        ("GET /", f"{base}/"),
    ]

    any_ok = False
    for name, url in checks:
        ok, detail = try_get(url)
        status = "✓ 通过" if ok else "✗ 失败"
        print(f"[{status}] {name}")
        print(f"  {detail.replace(chr(10), chr(10) + '  ')}")
        print()
        if ok:
            any_ok = True

    print("[...] POST /v1/chat/completions（实际调用，可能需 10-120 秒）")
    ok, detail = try_post_chat(base, model)
    print(f"[{'✓ 通过' if ok else '✗ 失败'}] 对话测试")
    print(f"  {detail}")
    print()

    if not any_ok and not ok:
        print("-" * 60)
        print("全部失败时的常见原因：")
        print("  1. IP/端口不对 — 在 Jetson 上执行: ss -tlnp | grep -E '8080|11434'")
        print("  2. 防火墙 — Jetson 需监听 0.0.0.0，不能仅 127.0.0.1")
        print("  3. 服务未启动 — 确认 llama-server / Ollama 进程在跑")
        print("  4. 用了 Ollama — 地址应为 http://IP:11434，模型名用 ollama list 里的名字")
        print("  5. Windows 与 Jetson 不在同一网段 — 先 ping Jetson IP")
        print()
        print("Jetson 上快速自检（SSH 登录后）：")
        print("  curl -s http://127.0.0.1:8080/v1/models")
        print("  curl -s http://127.0.0.1:8080/v1/chat/completions \\")
        print('    -H "Content-Type: application/json" \\')
        print('    -d \'{"model":"local-model","messages":[{"role":"user","content":"hi"}]}\'')
        return 1

    if any_ok and not ok:
        print("-" * 60)
        print("服务可达但对话失败，常见原因：")
        print("  1. LLAMA_MODEL 名称不对 — 看 /v1/models 返回的 id")
        print("  2. 模型还在加载 / 显存不足 — 看 Jetson 上 server 日志")
        print("  3. 首次推理较慢 — 多等一会或加大 timeout")
        return 1

    print("模型可用，可以运行 python web.py 或 python demo.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
