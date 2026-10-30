# 修改说明（不是 Skill）

用户用自然语言提出改动时，规则转换智能体先读本目录说明，再判断改：

- `ai/workflows/*.yaml`：审查流程（步骤顺序、要不要 YOLO、要不要某步抽取）
- `ai/rules/*.yaml`：审什么（比对字段、算子参数）

默认只改 Skill。只有流程真的变了才改 workflow，且只能使用已登记的 step。
