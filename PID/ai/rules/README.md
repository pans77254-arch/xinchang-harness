# 审查规则目录

每个审查点 = 一份 YAML。复制 `_template.yaml` 改 `id` 后即可被总控加载。

- 已启用示例：`form.toc_index` / `form.title_block` / `form.seq_stage_count` / `form.pid_paper` / `form.pid_seq` / `form.notes_typo`
- 下划线开头的文件不是审查点（`_template.yaml` 模板、`_notes_glossary.yaml` 错别字白名单），加载器会跳过
- 占位未启用：`pid.connectivity` / `site.fire_distance`（等算法组抽出对应工件后再把 `enabled: true`）
- 禁止在本目录写 Python；禁止发明未在 `ai/tools/operators.py` 登记的 `op`
