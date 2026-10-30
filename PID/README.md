#工程图纸智能审查 · 框架骨架

给开发人员克隆的基线仓库。目录索引一致性已接通：流程由 `ai/workflows/form.toc_index.yaml` 编排；Skill 决定审什么。Word 整页 PNG 交给大模型；PDF 先用 `best.pt` 裁右下角图框再抽取。自然语言改规则时，转换智能体判断改 Skill 还是 workflow。其余审查点的版面检测仍是接口桩。

请先读 **[开发指南.md](开发指南.md)**（放哪、什么文件不能动、怎么加审查点）。

```text
前端 Vue3  →  后端 FastAPI（后接 RuoYi）  →  ai.graph.invoke(task)
                                              detect → extract → review → validate
审查点 = ai/rules/*.yaml
工具   = ai/tools/*（PDF 转 PNG、字符比对；YOLO 与大模型在智能体里）
```

```bash
pip install -r requirements.txt
python scripts/smoke.py
python scripts/run_toc_index.py --folder "<含目录.doc 的文件夹>"
langgraph dev
```
