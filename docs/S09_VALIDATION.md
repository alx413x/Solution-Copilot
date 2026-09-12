# S09 端到端验收与交付记录

日期：2026-09-12；输入 S07/S08 未提交工作区，main，当前任务，ponytail full。状态：review。

## 目标与范围

从零复现“创建客户 → 上传资料 → 提取需求 → 人工确认 → 方案编排两门 → 逐章生成 → 人工编辑 → 质量校验 → Markdown/DOCX 导出下载”的完整链路，并以脱敏合成数据验证隔离、恢复与 AI 质量证据。

## 脱敏数据集（`evals/s09/`）

- `meeting-1.md`/`meeting-2.md`/`meeting-3.md`：三份合成售前会议纪要，覆盖背景、痛点、目标、功能、集成、安全合规、约束、验收指标八类。
- `conflict.md`：预算冲突材料（100 万元 → 80 万元），要求显式解决。
- `expected.json`：八类召回标签、`must_cover` 主张、`forbidden_promises`（自动报价、自动签约、识别准确率 100%）、冲突期望及指标口径说明。
- 检索评测复用 `evals/s03-corpus.json` 与 `evals/s03-results.json`。

合成数据不含真实客户信息；验收明确“模型建议和摘录匹配不能代替逐条人工支持度标注”。

## 复现方式

```bash
# 基础设施
docker compose -f infra/compose.yaml up -d
uv run alembic upgrade head
uv run python -m scripts.prepare_embeddings      # 首次，缓存 BGE revision
# API + Worker + Web（三个终端）见 README
uv run python -m scripts.smoke_s09               # 需要 .env 中的 DeepSeek 配置
```

`scripts/smoke_s09.py` 全部以 `assert` 断言，失败即非零退出；结果写入 `evals/s09-results.json`，导出产物写入 `.local/s09/`（被忽略）。

## 验收结果（`evals/s09-results.json`）

| 指标 | 结果 |
| --- | --- |
| 端到端耗时 | 52.16 秒（真实 DeepSeek + 本地 BGE + Celery） |
| 文档处理 | `ready` |
| 需求提取 | 8 项；八类召回 1.0；quote 逐字匹配率 1.0 |
| 方案发布版本 | 7 |
| 质量覆盖率 | 100%（advisory，模型评估） |
| 质量规则命中 | 12 条问题，含 `citation_scope`、`unsupported_promise`、`contradiction`、`acceptance_metric`、`factual_citation`、`incomplete_section`、`required_clarification`、`unverified_content` |
| 语义引用支持率 | 未测（需逐条人工标注，不伪造分数） |
| 越权下载 | 匿名请求 401，`unauthorized_download_denied=true` |
| 历史不可变 | 编辑后旧版本快照不变，`history_immutable=true` |
| 导出 | Markdown 14648 字节、DOCX 42154 字节；均含全部章节标题、引用摘录与“参考资料” |

导出文件校验：

- `.local/s09/solution.md`：UTF-8，含版本提示、章节顺序、章内引用编号 `[n]`、待核实标记及文末参考资料。
- `.local/s09/solution.docx`：`Microsoft OOXML`，`python-docx` 可打开，4 个 Heading 段落、57 段落，标题级别正确。

## 自动化回归（2026-09-12）

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| PostgreSQL 测试 | `RUN_DB_TESTS=1 uv run pytest -q` | 41 passed |
| Python 静态检查 | `uv run ruff check apps backend scripts tests` | 通过 |
| Python 格式 | `uv run ruff format --check apps backend scripts tests` | 通过 |
| 前端格式 | `pnpm format:check` | 通过 |
| 前端类型 | `pnpm check` | 通过 |
| 生产构建 | `pnpm build` | 通过 |
| 迁移一致性 | `uv run alembic check` | `No new upgrade operations detected`，head `7ca82ebc4d6b` |

按阶段：S01 9、S02 11、S03 2、S04 3、S05 3、S06 3、S07 4、S08 3、健康检查 3。

## 未验证项 / 已知限制

- **浏览器手工与无障碍**：本次未执行 UI 工具验证，未做完整 axe 或屏幕阅读器审计；仅确认生产构建含全部路由。
- **真实 OIDC**：仍使用开发身份演示，生产登录跳转未联调。
- **供应商生产数据策略与部署**：未验收；生成调用会把已确认需求与本次授权检索结果发送到配置的 DeepSeek。
- **DLP**：客户泄漏检查只做已登记同组织其他客户名称的正文精确匹配，非完整 DLP。
- **AI 质量**：`category recall` 对照人工标签，`quote match` 不等于语义支持；质量覆盖为模型评估（advisory），需人工核实。语义引用支持率未测。
- **检索规模**：合成小语料、精确向量扫描，无 reranker/查询改写；OCR 未实现。
- **文档保真**：表格仅支持简单矩形表（≤50×20，无合并单元格/自定义列宽）；无复杂 PDF 表格结构保真。
- **生产部署与完整无障碍审计**仍未验收。

## 交付与交接

- 启动命令、S00–S08 功能说明及边界见 [README](../README.md)。
- 各阶段证据：[S00](S00_VALIDATION.md)、[S01](S01_VALIDATION.md)、[S02](S02_VALIDATION.md)、[S03](S03_VALIDATION.md)、[S04](S04_VALIDATION.md)、[S05](S05_VALIDATION.md)、[S06](S06_VALIDATION.md)、[S07](S07_VALIDATION.md)、[S08](S08_VALIDATION.md)。
- 决策：[D019](../DECISIONS.md)（S07）、[D020](../DECISIONS.md)（S08）。
