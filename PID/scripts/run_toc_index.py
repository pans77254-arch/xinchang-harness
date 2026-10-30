"""跑目录索引一致性。用法：python scripts/run_toc_index.py --folder <设计文件目录>"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai.graph.controller import invoke


def main() -> None:
    parser = argparse.ArgumentParser(description="目录索引一致性审查")
    parser.add_argument("--folder", required=True, help="含目录文件和各设计文件的文件夹")
    args = parser.parse_args()
    result = invoke(
        {
            "task_id": "toc-index",
            "folder": args.folder,
            "skill_ids": ["form.toc_index"],
            "storage_dir": args.folder,
        }
    )
    payload = {
        "logs": result.get("logs"),
        "validation": result.get("validation"),
        "issues": result.get("issues"),
        "catalog": (result.get("artifacts") or {}).get("toc"),
        "files": ((result.get("artifacts") or {}).get("title_block") or {}).get("items"),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
