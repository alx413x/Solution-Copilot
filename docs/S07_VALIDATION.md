# S07 方案生成与编辑验收记录

日期：2026-09-10，最终核对 2026-09-12；输入 `fc9c8d4`，main，当前任务，ponytail full。状态：review（实现与自动/真实链路证据齐备；浏览器证据沿用历史记录，见“未在本次复现”）。

## 实现范围

- 迁移 `7ca82ebc4d6b`：项目唯一方案与不可变完整章节版本。
- S06 编排输入校验、可编辑大纲、逐章生成与单章重生成。
- 版本内引用快照、受限 Tiptap JSON 人工保存和历史只读查看。
- 复用 GenerationRun、dispatcher、SSE 与 DeepSeek JSON 适配器；事务外调用和发布 fencing。

## 验收证据（2026-09-12 复现）

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| PostgreSQL 测试 | `RUN_DB_TESTS=1 uv run pytest -q` | 41 passed（S07 4 项：生命周期/引用/恢复、人工编辑校验与幂等、迟到结果 fencing、过期 attempt 不得发布） |
| Python 静态检查 | `uv run ruff check apps backend scripts tests` | 通过 |
| Python 格式 | `uv run ruff format --check apps backend scripts tests` | 通过 |
| 前端格式 | `pnpm format:check` | 通过 |
| 前端类型 | `pnpm check` | 通过 |
| 生产构建 | `pnpm build` | 通过，含 `/projects/[projectId]/solution` 路由 |
| 迁移一致性 | `uv run alembic check` | `No new upgrade operations detected` |

真实链路（`evals/s07-results.json`，2026-09-10）：Web→API→dispatcher→Celery→DeepSeek→PostgreSQL，2 章、21 条引用、49.14 秒，最高发布版本 7；模型记录 prompt version、usage 与 latency。

自动测试覆盖（`tests/test_s07.py`）：

- 生命周期：创建方案、生成大纲、确认后逐章生成、引用快照、单章重生成保留其他章、历史只读。
- 人工保存：受限 Tiptap JSON 校验、版本 version 冲突 409、request 幂等、人工编辑后该章引用降为 `unverified`。
- 恢复与 fencing：迟到模型结果、过期 attempt 不得发布或污染下一章；多章部分失败保留已发布章节。

## 未在本次复现

- 浏览器手工验收（大纲增删排序、逐章/单章重生成、Tiptap 保存、历史只读、刷新恢复、键盘与四断点响应式）在 S07 实现当日记录，本次未重新执行 UI 工具验证，故不追加新结论。
- 真实 OIDC、供应商生产数据策略、完整 axe 与屏幕阅读器审计仍未验收。

## 当前边界

- `partial` 仅证明 quote 逐字匹配，不证明主张获得语义支持；人工编辑后该章引用为 `unverified`。
- S07 不含完整质量检查、Markdown/DOCX 导出或下载；由 S08 承接，证据见 [S08 验收记录](S08_VALIDATION.md)。
- 每方案最多 20 章、200 版本；每章序列化后最多 100000 字符、2000 节点、深度 12。
