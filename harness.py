"""信创版 Harness v0.1 — ReAct 运行时循环"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Protocol

import yaml

from tools import TOOL_REGISTRY

logger = logging.getLogger(__name__)

FEW_SHOT = """
正确示例（每轮只输出下面这一种，不要一次输出多步）：
{"action": "search_docs", "args": {"keyword": "AI 中间层"}}
"""


class ModelAPI(Protocol):
    def chat(self, prompt: str) -> str: ...


class XinchangHarness:
    def __init__(self, model_api: ModelAPI, tools_config: str | Path = "tools.yaml") -> None:
        self.model_api = model_api
        self.tools = self.load_tools(tools_config)

    def load_tools(self, config_path: str | Path) -> list[dict[str, Any]]:
        path = Path(config_path)
        with path.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        tools = raw.get("tools", [])
        enabled: list[dict[str, Any]] = []
        for tool in tools:
            if not tool.get("enabled", True):
                logger.info("跳过未启用工具: %s", tool.get("name"))
                continue
            name = tool.get("name")
            if name not in TOOL_REGISTRY:
                logger.warning("tools.yaml 声明了未注册的工具: %s", name)
                continue
            enabled.append(tool)
        if not enabled:
            raise RuntimeError("没有可用工具，请检查 tools.yaml 与 TOOL_REGISTRY")
        return enabled

    def build_prompt(self, task: str, history: str) -> str:
        tool_lines: list[str] = []
        for tool in self.tools:
            params = tool.get("parameters") or {}
            param_desc = ", ".join(f"{k}: {params[k].get('description', '')}" for k in params)
            tool_lines.append(f"- {tool['name']}: {tool['description']}（参数: {param_desc}）")

        tools_desc = "\n".join(tool_lines)
        return f"""你是政企内网调度器。不要解释，不要输出思考过程，不要输出 <think>。

可用工具：
{tools_desc}

硬性规则：
1. 每一轮只输出一个 JSON，不要 markdown，不要多段。
2. 调工具：{{"action":"工具名","args":{{...}}}}
3. 结束：{{"action":"final_answer","content":"答案"}}
4. 流程固定：search_docs → read_file → check_classification → check_sensitive → suggest_desensitization → final_answer。每步只做一次。
5. check_classification / check_sensitive / suggest_desensitization 的 text 参数直接填 read_file 读到的文档正文，不要提炼、不要套 JSON、不要复制之前的输出。
6. 同一工具相同参数禁止再调。全部检查完成后必须立刻 final_answer。
7. 执行历史里已有结果就直接用，不要再搜一遍。

{FEW_SHOT}

任务：{task}

执行历史：
{history if history else "（尚无历史，请先 search_docs）"}
"""

    def run(self, task: str, max_steps: int = 6) -> str:
        """执行 ReAct 循环，返回最终答案。"""
        answer = "任务未完成"
        for event in self.iter_run(task, max_steps=max_steps):
            if event["event"] == "done":
                answer = event["answer"]
            elif event["event"] == "max_steps":
                answer = event["message"]
        return answer

    def iter_run(self, task: str, max_steps: int = 6):
        """逐步 yield 事件，供 Web SSE / 日志使用。"""
        history = ""
        seen_calls: set[str] = set()
        used_tools: set[str] = set()
        parse_fails = 0

        for step in range(max_steps):
            step_no = step + 1
            yield {"event": "step_start", "step": step_no}

            prompt = self.build_prompt(task, history)
            logger.info("=== 第 %d 步：请求模型 ===", step_no)
            raw = self.model_api.chat(prompt)
            logger.info("模型原始输出:\n%s", raw)
            yield {"event": "model_output", "step": step_no, "raw": raw}

            action = self.parse_action(raw)
            logger.info("解析结果: %s", action)
            # 提前清理 check 类工具的 text，让 action 事件也展示干净参数
            if action.get("action") in ("check_classification", "check_sensitive", "suggest_desensitization"):
                action["args"] = self._clean_check_text(action.get("args") or {}, history)
            yield {"event": "action", "step": step_no, "action": action}

            if action.get("action") == "final_answer":
                answer = str(action.get("content") or "").strip() or history or raw
                yield {"event": "done", "step": step_no, "answer": answer}
                return

            if action.get("action") == "parse_error":
                parse_fails += 1
                auto = self._auto_next(task, used_tools, history)
                yield {
                    "event": "parse_error",
                    "step": step_no,
                    "message": "小模型未输出合法 JSON，已按固定流程自动执行下一步（demo 兜底）。",
                }
                action = auto
                yield {"event": "action", "step": step_no, "action": action}

                if action.get("action") == "final_answer":
                    yield {
                        "event": "done",
                        "step": step_no,
                        "answer": str(action.get("content") or self._fallback_answer(history, "已结束。")),
                    }
                    return


            tool_name = str(action.get("action") or "")
            if not tool_name:
                parse_fails += 1
                msg = f"\n第{step_no}步：缺少 action 字段\n"
                history += msg
                yield {"event": "error", "step": step_no, "message": msg.strip()}
                continue

            tool_args = action.get("args") or {}
            if not isinstance(tool_args, dict):
                msg = f"\n第{step_no}步：args 必须是对象\n"
                history += msg
                yield {"event": "error", "step": step_no, "message": msg.strip()}
                continue

            call_key = f"{tool_name}:{json.dumps(tool_args, ensure_ascii=False, sort_keys=True)}"
            if call_key in seen_calls or tool_name in used_tools:
                yield {
                    "event": "done",
                    "step": step_no,
                    "answer": self._fallback_answer(
                        history,
                        f"检测到重复调用 {tool_name}，已停止循环并根据已有结果作答。",
                    ),
                }
                return

            tool_fn = TOOL_REGISTRY.get(tool_name)
            if tool_fn is None:
                msg = f"\n第{step_no}步：工具「{tool_name}」不存在，请从 search_docs / read_file / check_sensitive / final_answer 中选择\n"
                history += msg
                yield {"event": "error", "step": step_no, "message": msg.strip()}
                continue

            try:
                result = tool_fn(**tool_args)
            except TypeError as exc:
                result = f"参数错误：{exc}"
            except Exception as exc:  # noqa: BLE001
                result = f"工具执行出错：{exc}"

            seen_calls.add(call_key)
            used_tools.add(tool_name)
            history += f"\n第{step_no}步：调用 {tool_name}({tool_args}) → 结果：{result}\n"
            logger.info("工具结果: %s", result)
            yield {
                "event": "tool_result",
                "step": step_no,
                "tool": tool_name,
                "args": tool_args,
                "result": result,
            }

            if (
                "search_docs" in used_tools
                and "read_file" in used_tools
                and "check_classification" in used_tools
                and "check_sensitive" in used_tools
                and "suggest_desensitization" in used_tools
            ):
                yield {
                    "event": "done",
                    "step": step_no,
                    "answer": self._fallback_answer(history, ""),
                }
                return

        yield {
            "event": "max_steps",
            "message": self._fallback_answer(history, "已达最大步数，停止循环。"),
        }

    @staticmethod
    def _extract_doc_from_history(history: str) -> str:
        """从 history 提取 read_file 返回的文档正文。"""
        m = re.search(r"调用 read_file\([^)]+\) → 结果：\n?(.*?)(?=\n第\d+步：|$)", history, re.DOTALL)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _clean_check_text(tool_args: dict, history: str) -> dict:
        """check_sensitive 的检查对象统一为 read_file 读到的完整文档。

        语义上，敏感词检查应查文档本身（密级标注、备注里的「严禁外传」
        都是敏感信息），而不是模型随意提炼的要点。小模型在第 3 步常乱填
        text（塞要点、塞嵌套 JSON、塞半截），这里做确定性兜底：统一改用
        history 里 read_file 返回的完整文档作为检查对象。
        """
        doc = XinchangHarness._extract_doc_from_history(history)
        if doc:
            tool_args = dict(tool_args)
            tool_args["text"] = doc[:2000]
        return tool_args

    @staticmethod
    def _auto_next(task: str, used_tools: set[str], history: str) -> dict[str, Any]:
        """1.5B 吐不出 JSON 时，按固定审查流程往下走。"""
        if "search_docs" not in used_tools:
            keyword = "涉密" if "涉密" in task else task[:20]
            return {"action": "search_docs", "args": {"keyword": keyword}}
        if "read_file" not in used_tools:
            path_m = re.search(r"docs/[^\"'\s]+\.md", history)
            path = path_m.group(0) if path_m else "docs/涉密项目方案.md"
            return {"action": "read_file", "args": {"path": path}}
        doc = XinchangHarness._extract_doc_from_history(history) or history[-4000:]
        if "check_classification" not in used_tools:
            return {"action": "check_classification", "args": {"text": doc}}
        if "check_sensitive" not in used_tools:
            return {"action": "check_sensitive", "args": {"text": doc}}
        if "suggest_desensitization" not in used_tools:
            return {"action": "suggest_desensitization", "args": {"text": doc}}
        return {
            "action": "final_answer",
            "content": XinchangHarness._fallback_answer(history, "模型未能输出 JSON，已用工具结果汇总。"),
        }

    @staticmethod
    def _fallback_answer(history: str, note: str) -> str:
        """从执行历史中提取结构化答案；若提取失败则返回原始历史。"""
        answer = XinchangHarness._structured_answer(history)
        if answer:
            return answer
        hist = history.strip() or "（尚无工具结果）"
        return f"{note}\n\n依据执行历史：\n{hist}"

    @staticmethod
    def _structured_answer(history: str) -> str:
        """从 history 提取审查结果，拼成保密审查报告。"""
        # 提取 read_file 返回的文档正文
        doc_match = re.search(
            r"调用 read_file\([^)]+\) → 结果：\n?(.*?)(?=\n第\d+步：|$)",
            history,
            re.DOTALL,
        )
        if not doc_match:
            return ""
        doc_text = doc_match.group(1).strip()

        # 取文档标题
        title_match = re.search(r"#\s+(.+)", doc_text)
        doc_title = title_match.group(1).strip() if title_match else "内网文档"

        # 1. 密级标注结果
        class_line = "（密级检查结果未知）"
        class_m = re.search(r"调用 check_classification[^→]*→ 结果：(.+?)(?=\n第\d+步：|$)", history, re.DOTALL)
        if class_m:
            raw = class_m.group(1).strip()
            marked = re.search(r"'标注密级':\s*'([^']*)'", raw)
            concl = re.search(r"'结论':\s*'([^']*)'", raw)
            if marked:
                class_line = f"{marked.group(1)} —— {concl.group(1) if concl else ''}"

        # 2. 涉密内容结果
        sensitive_line = "（涉密检查结果未知）"
        sensitive_match = re.search(r"'命中涉密内容':\s*\[([^\]]*)\]", history)
        if sensitive_match:
            raw_words = sensitive_match.group(1)
            words = [w.strip().strip("'\"") for w in raw_words.split(",") if w.strip()]
            sensitive_line = f"命中 {len(words)} 处：**{'、'.join(words)}**" if words else "未发现涉密内容"
        else:
            no_sensitive = re.search(r"调用 check_sensitive[^→]+→ 结果：未发现涉密内容", history)
            if no_sensitive:
                sensitive_line = "未发现涉密内容"

        # 3. 脱敏建议结果
        desen_line = "（脱敏建议未知）"
        desen_m = re.search(r"调用 suggest_desensitization[^→]*→ 结果：(.+?)(?=\n第\d+步：|$)", history, re.DOTALL)
        if desen_m:
            raw = desen_m.group(1).strip()
            if raw.startswith("[") and raw.endswith("]"):
                items = [w.strip().strip("'\"") for w in raw.strip("[]").split(",") if w.strip()]
                desen_line = "\n".join(f"- {it}" for it in items) if items else "未发现需脱敏的信息"
            elif "未发现" in raw:
                desen_line = "未发现需脱敏的信息"
            else:
                desen_line = raw

        return (
            f"## 保密审查报告 —《{doc_title}》\n\n"
            f"**1. 密级标注**：{class_line}\n\n"
            f"**2. 涉密内容**：{sensitive_line}\n\n"
            f"**3. 脱敏建议**：\n{desen_line}"
        )

    @staticmethod
    def parse_action(raw: str) -> dict[str, Any]:
        """提取 JSON；R1 小模型失败时用正则从文本里捞 action。"""
        text = raw.strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE)
        if "```" in text:
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if match:
                text = match.group(1)

        snippet = XinchangHarness._first_json_object(text)
        if snippet:
            parsed = XinchangHarness._loads_json(snippet)
            if parsed:
                return parsed

        recovered = XinchangHarness._recover_action(raw)
        if recovered:
            return recovered
        return {"action": "parse_error", "raw": raw}

    @staticmethod
    def _loads_json(snippet: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(snippet)
        except json.JSONDecodeError:
            cleaned = re.sub(r",\s*}", "}", snippet)
            cleaned = re.sub(r",\s*]", "]", cleaned)
            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError:
                return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _recover_action(raw: str) -> dict[str, Any] | None:
        """从半残输出里识别工具名和参数。"""
        blob = raw.replace("'", '"')
        tool_names = r"(search_docs|read_file|check_classification|check_sensitive|suggest_desensitization|final_answer)"
        act = re.search(
            r"action\s*[\"']?\s*[:=]\s*[\"']?" + tool_names,
            blob,
            re.IGNORECASE,
        )
        if not act:
            # 模型有时只写出工具名
            only = re.search(r"\b" + tool_names + r"\b", blob)
            if not only:
                return None
            name = only.group(1)
        else:
            name = act.group(1)

        if name == "search_docs":
            kw = re.search(r"(?:keyword|关键词)\s*[\"']?\s*[:=]\s*[\"']([^\"']+)", blob)
            if not kw:
                kw = re.search(r"search_docs[^\"']*[\"']([^\"']{2,40})[\"']", blob)
            keyword = kw.group(1).strip() if kw else "涉密"
            return {"action": "search_docs", "args": {"keyword": keyword}}
        if name == "read_file":
            path = re.search(r"(?:path|路径)\s*[\"']?\s*[:=]\s*[\"']([^\"']+)", blob)
            if not path:
                path = re.search(r"(docs/[^\"'\s]+\.md)", blob)
            return {"action": "read_file", "args": {"path": path.group(1) if path else "docs/涉密项目方案.md"}}
        if name in ("check_classification", "check_sensitive", "suggest_desensitization"):
            textm = re.search(r"(?:text|文本)\s*[\"']?\s*[:=]\s*[\"'](.+?)[\"']", blob, re.DOTALL)
            return {"action": name, "args": {"text": (textm.group(1) if textm else blob)[:2000]}}
        content = re.search(r"(?:content|答案)\s*[\"']?\s*[:=]\s*[\"'](.+?)[\"']", blob, re.DOTALL)
        return {"action": "final_answer", "content": content.group(1) if content else blob[-1500:]}

    @staticmethod
    def _first_json_object(text: str) -> str | None:
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        in_str = False
        escape = False
        for i, ch in enumerate(text[start:], start):
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None
