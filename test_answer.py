from harness import XinchangHarness

history = """
第1步：调用 search_docs({'keyword': 'AI 中间层'}) → 结果：[{'title': 'AI中间层讨论纪要.md', 'path': 'docs/AI中间层讨论纪要.md'}]
第2步：调用 read_file({'path': 'docs/AI中间层讨论纪要.md'}) → 结果：
# AI 中间层讨论纪要

## 讨论要点

1. **统一接口**：上层业务只调用 OpenAI 兼容 API，路由层负责把请求分发到 DCU / Jetson / CPU。
2. **数据不出域**：模型与文档均部署在内网，禁止调用外部 SaaS 大模型。
3. **小模型 + 工具**：本地小模型能力有限，需通过 Harness 思想补能力——知识库检索、文档读取、合规检查由工具完成，模型只做调度。

第3步：调用 check_sensitive({'text': '...'}) → 结果：{'命中敏感词': ['内部资料']}
"""

print(XinchangHarness._fallback_answer(history, ""))
