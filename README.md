# 信创版 Harness v0.1

借鉴 DeepSeek Harness 的「声明式配置 + seam 接口」思想，验证：**本地小模型 + 工具补能力 = 政企内网多步骤 Agent**。

## 快速开始

### 命令行 Demo

```bash
cd xinchang-harness
pip install -r requirements.txt

# Jetson 上 llama-server 默认地址（可改）
set LLAMA_SERVER_URL=http://192.168.110.74:8080

python demo.py -v
```

### Web 界面

在项目目录执行（推荐，后台启停）：

```powershell
cd E:\360MoveData\Users\18134\Desktop\xinchang-harness
$env:LLAMA_SERVER_URL = "http://192.168.110.74:8080"

python serve.py start      # 启动
python serve.py status     # 是否在跑
python serve.py stop       # 停止
python serve.py restart    # 重启
```

浏览器打开 **http://127.0.0.1:8765**。日志在 `logs/web.log`。

前台调试仍可用 `python web.py`（窗口里 Ctrl+C 停止）。

如果 `python serve.py start` 没有任何输出，改用：

```powershell
.\serve.cmd start
.\serve.cmd status
.\serve.cmd stop
```

`serve.cmd` 会强制打印 Python 解释器路径、执行动作和退出码，便于定位问题。

可选环境变量：

| 变量 | 说明 | 默认 |
|------|------|------|
| `WEB_HOST` | Web 监听地址 | `0.0.0.0` |
| `WEB_PORT` | Web 端口 | `8765` |

## 目录

| 文件 | 作用 |
|------|------|
| `tools.yaml` | 声明式工具清单（改描述 / 启停工具） |
| `tools.py` | 工具实现 + `TOOL_REGISTRY` |
| `harness.py` | ReAct 循环（支持逐步事件 `iter_run`） |
| `model.py` | llama-server OpenAI 兼容适配 |
| `demo.py` | 命令行演示入口 |
| `web.py` | Web 服务（FastAPI + SSE 流式展示） |
| `serve.py` | 一键启动/停止/状态/重启 |
| `serve.cmd` | Windows 诊断启动器（强制打印输出） |
| `static/index.html` | Web 前端页面 |
| `docs/` | 内网测试文档 |

## 环境变量

| 变量 | 说明 | 默认 |
|------|------|------|
| `LLAMA_SERVER_URL` | llama-server 基址 | `http://192.168.110.74:8080` |
| `LLAMA_MODEL` | 模型名（与 server 配置一致） | `local-model` |

## 声明式边界

- **只改 `tools.yaml`**：工具描述、参数说明、`enabled` 开关。
- **新工具实现**：在 `tools.py` 写函数并登记到 `TOOL_REGISTRY`，再在 yaml 里声明。

## 演示场景

默认任务：从内网文档检索「AI 中间层」讨论 → 读文档 → 整理要点 → 敏感词检查。

预期调用链：`search_docs` → `read_file` → `check_sensitive` → `final_answer`。

## 小模型提示

若 JSON 输出不稳定，可尝试：

1. 换更大模型（Qwen2.5-3B/7B）
2. 加 `-v` 看每步解析日志
3. 调低 `model.py` 中 `temperature`（默认 0.1）

## 边界

v0.1 为最小原型：单轮任务、无会话记忆、无向量检索、无审批链。详见技术方案文档。
