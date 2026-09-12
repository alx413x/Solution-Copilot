# S08 校验与导出验收记录

日期：2026-09-11，最终核对 2026-09-12；输入 S07 未提交工作区，main，当前任务，ponytail full。状态：review（实现与自动/真实链路证据齐备；浏览器证据沿用历史记录，见“未在本次复现”）。

## 实现范围

- 复用 `GenerationRun`/dispatcher 的 `verify` 与 `export` 任务，不新建表；`payload.kind` 为 `verify` 或 `export`。
- 质量检查绑定不可变方案版本和需求档案版本；导出绑定方案版本；请求 UUID 幂等。
- 页面可启动任务、轮询状态、定位章节问题及下载完成文件。
- Markdown 与 DOCX 导出，保留章节顺序、编辑器结构、章内引用编号、待核实标记及文末按章参考资料。
- 私有对象存储与下载：每次下载重验 ACL，校验 SHA-256，响应 `private, no-store`。

## 验收证据（2026-09-12 复现）

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| PostgreSQL 测试 | `RUN_DB_TESTS=1 uv run pytest -q` | 41 passed（S08 3 项，见下） |
| Python 静态检查 | `uv run ruff check apps backend scripts tests` | 通过 |
| Python 格式 | `uv run ruff format --check apps backend scripts tests` | 通过 |
| 前端格式 | `pnpm format:check` | 通过 |
| 前端类型 | `pnpm check` | 通过 |
| 生产构建 | `pnpm build` | 通过 |
| 迁移一致性 | `uv run alembic check` | `No new upgrade operations detected` |

自动测试覆盖（`tests/test_s08.py`）：

- `test_verify_validates_locations_coverage_and_request_identity`：质量结果含 `rule_id`/`severity`/`section_id`/`explanation`/`suggestion`；覆盖率映射必须不重不漏包含已确认需求；章节 ID 必须存在；request UUID 幂等与冲突 409。
- `test_exports_are_openable_immutable_and_private`：
  - Markdown 保留章节顺序、`###` 二级标题、加粗/斜体、有序/无序列表、代码块、表格；转义 `<script>`；文末含“参考资料”。
  - 导出排队后编辑方案不改变已发布导出内容（不可变）。
  - DOCX 经 `python-docx` 重新打开：Title 段落、Heading 2、`No Spacing` 代码样式、项目符号与编号列表、`Table Grid` 表格内容与单元格加粗/斜体均正确。
  - owner/member/viewer 可下载；其他组织返回 404；非授权角色启动导出返回 403；撤销客户授权后旧下载地址返回 404。
  - 响应头 `cache-control: private, no-store`。
- `test_failed_cancelled_and_late_exports_never_download`：失败、取消及迟到 attempt 的产物不提供下载。

端到端（`evals/s09-results.json`，2026-09-12）：真实链路导出 Markdown 14648 字节、DOCX 42154 字节，两文件落地 `.local/s09/`；DOCX 含 4 个标题、57 段落，可正常打开；`unauthorized_download_denied=true`、`history_immutable=true`。

## 表格支持（原“待补齐”项已闭合）

`status` 此前记录表格编辑与导出“正在补齐”，现已实现并由测试覆盖：

- 服务端白名单接受 `table`/`tableRow`/`tableCell`/`tableHeader`，要求矩形表且最多 50 行、20 列，拒绝合并单元格和自定义列宽。
- 编辑器启用 `@tiptap/extension-table`（`TableKit`，`resizable: false`）。
- Markdown 导出为管道表格并保留表头加粗；DOCX 导出为 `Table Grid` 表格并保留单元格内加粗/斜体。

## 未在本次复现

- 浏览器手工验收（启动校验/导出、轮询、问题定位、下载、四断点与无障碍）在 S08 实现当日记录，本次未重新执行 UI 工具验证，故不追加新结论。
- 供应商生产数据策略、完整 DLP、生产 OIDC 与屏幕阅读器审计仍未验收。

## 当前边界

- 泄漏检查只做已登记同组织其他客户名称的正文精确匹配，不检测别名、改写或其他私密数据，不构成完整 DLP。
- 质量为辅助审核，不替代人工判断，不把引用摘录当作事实支持；方案或需求修改后需重新检查。
- 仅支持 Markdown 与 DOCX；不含 PDF、品牌 DOCX 模板或签名 URL。
