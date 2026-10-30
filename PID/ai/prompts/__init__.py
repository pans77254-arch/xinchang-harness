"""提示词库。正文只在本目录的 YAML 里，代码通过 render(id) 加载。"""

from ai.prompts.loader import load_prompt, render

__all__ = ["load_prompt", "render"]
