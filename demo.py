"""信创版 Harness v0.1 演示入口"""

from __future__ import annotations

import argparse
import logging
import sys

from harness import XinchangHarness
from model import LlamaServerModel

DEFAULT_TASK = (
    "从内网文档中找出涉密文件，做保密审查：检查密级标注、检查涉密内容、给出脱敏建议"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="信创版 Harness v0.1 Demo")
    parser.add_argument("--url", default=None, help="llama-server 地址，默认读环境变量 LLAMA_SERVER_URL")
    parser.add_argument("--task", default=DEFAULT_TASK, help="要执行的任务描述")
    parser.add_argument("--max-steps", type=int, default=10, help="ReAct 最大步数")
    parser.add_argument("-v", "--verbose", action="store_true", help="打印详细日志")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    model = LlamaServerModel(base_url=args.url)
    print(f"模型服务: {model.base_url}")
    print("检查 llama-server 连通性...")
    if not model.health_check():
        print(
            "警告: 无法确认 llama-server 健康状态，仍将尝试调用。\n"
            "请确认 Jetson 上服务已启动，或通过 --url 指定正确地址。",
            file=sys.stderr,
        )
    else:
        print("llama-server 可达。")

    harness = XinchangHarness(model)
    print("\n任务:", args.task)
    print("-" * 60)
    answer = harness.run(args.task, max_steps=args.max_steps)
    print("-" * 60)
    print("\n最终答案:\n")
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
