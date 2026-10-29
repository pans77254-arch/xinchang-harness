"""模型适配层：对接 Jetson / DCU 上的 llama-server（OpenAI 兼容 API）"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

# 强制模型只能输出四种合法 JSON，避免 1.5B/R1 乱写 <think>
ACTION_GRAMMAR = r"""
root ::= search | readfile | classify | check | desen | final
search ::= "{" ws "\"action\"" ws ":" ws "\"search_docs\"" ws "," ws "\"args\"" ws ":" ws "{" ws "\"keyword\"" ws ":" ws string ws "}" ws "}"
readfile ::= "{" ws "\"action\"" ws ":" ws "\"read_file\"" ws "," ws "\"args\"" ws ":" ws "{" ws "\"path\"" ws ":" ws string ws "}" ws "}"
check ::= "{" ws "\"action\"" ws ":" ws "\"check_sensitive\"" ws "," ws "\"args\"" ws ":" ws "{" ws "\"text\"" ws ":" ws string ws "}" ws "}"
classify ::= "{" ws "\"action\"" ws ":" ws "\"check_classification\"" ws "," ws "\"args\"" ws ":" ws "{" ws "\"text\"" ws ":" ws string ws "}" ws "}"
desen ::= "{" ws "\"action\"" ws ":" ws "\"suggest_desensitization\"" ws "," ws "\"args\"" ws ":" ws "{" ws "\"text\"" ws ":" ws string ws "}" ws "}"
final ::= "{" ws "\"action\"" ws ":" ws "\"final_answer\"" ws "," ws "\"content\"" ws ":" ws string ws "}"
string ::= "\"" ([^"\\] | "\\" ["\\/bfnrt])* "\""
ws ::= [ \t\n]*
"""


class LlamaServerModel:
    """llama-server OpenAI 兼容客户端。换 base_url 即可切换 Jetson / 海光 DCU。"""

    def __init__(
        self,
        base_url: str | None = None,
        model: str = "local-model",
        temperature: float = 0.0,
        max_tokens: int = 160,
        timeout: int = 180,
    ) -> None:
        self.base_url = (base_url or os.getenv("LLAMA_SERVER_URL", "http://192.168.110.74:8080")).rstrip("/")
        self.model = os.getenv("LLAMA_MODEL", model)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    def chat(self, prompt: str) -> str:
        """优先走 /completion + GBNF，绕过 R1 的 <think> 模板。"""
        forced = prompt.rstrip() + "\n只输出 JSON，不要思考：\n"
        text = self._completion(forced)
        if text:
            return text
        return self._chat_completions(forced)

    def _completion(self, prompt: str) -> str:
        url = f"{self.base_url}/completion"
        payload: dict[str, Any] = {
            "prompt": prompt,
            "n_predict": self.max_tokens,
            "temperature": self.temperature,
            "grammar": ACTION_GRAMMAR,
            "cache_prompt": True,
        }
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout)
            if not resp.ok:
                logger.warning("llama /completion HTTP %s: %s", resp.status_code, resp.text[:400])
                return ""
            data = resp.json()
            return str(data.get("content") or data.get("response") or "").strip()
        except requests.RequestException as exc:
            logger.warning("llama /completion 失败，回退 chat: %s", exc)
            return ""

    def _chat_completions(self, prompt: str) -> str:
        url = f"{self.base_url}/v1/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "grammar": ACTION_GRAMMAR,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        resp = requests.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        return str(msg.get("content") or msg.get("reasoning_content") or "")

    def health_check(self) -> bool:
        """检查 llama-server 是否可达。"""
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=5)
            return resp.status_code == 200
        except requests.RequestException:
            try:
                resp = requests.get(f"{self.base_url}/v1/models", timeout=5)
                return resp.status_code == 200
            except requests.RequestException:
                return False
