# S02 文档处理验收

日期：2026-09-07 至 2026-09-08。工作区 main；输入 `9a185bd`。本地功能验收通过，实现整合提交 `43589a3`，最终状态 done。

## 交付

- Alembic `9094c79bd5c7`：documents、document_chunks、jobs；作用域约束、组织组合外键、同作用域 SHA256 去重、generation 唯一约束。
- 私有上传与下载、格式/大小/签名校验、四格式文本提取与定位、原子替换分块。
- PostgreSQL jobs/outbox、独立 dispatcher、执行时鉴权、重复投递幂等、续租/过期恢复、失败重试、取消 fencing、删除补偿。
- 组织、客户、项目资料页：上传、轮询进度、分块预览、下载、重新解析、重试、取消、停用与删除。
- D010/D012 S02 边界收敛、D015 解析契约；`parsed` 与 S03 `ready` 区分。

## 实际验证

| 验证 | 命令或操作 | 结果 |
| --- | --- | --- |
| 数据库迁移 | `uv run alembic upgrade head`、`uv run alembic check` | 无未生成的模型变更 |
| Python | `uv run ruff check backend apps/api apps/worker scripts tests migrations` | 通过 |
| 格式 | `uv run ruff format --check backend apps/api apps/worker scripts tests migrations` | 通过 |
| 集成测试 | `RUN_DB_TESTS=1 uv run --group test pytest -q` | 23 passed；真实 PostgreSQL 隔离 schema |
| 契约 | `pnpm contracts` | OpenAPI/TypeScript 已更新 |
| Web | `pnpm check`、`pnpm format:check`、`pnpm build` | 通过 |
| 四格式实链路 | `uv run --group test python -m scripts.smoke_s02` | TXT/MD/PDF/DOCX 上传、去重、真实 Worker、来源、下载和删除通过 |
| 前阶段回归 | `uv run --group test python -m scripts.smoke_s01`、`uv run --group test python -m scripts.smoke` | 会话/CSRF/CRUD、API/Web 健康、Worker 三基础设施、私有存储匿名拒绝通过 |
| 浏览器 | 登录后上传 `docs/fixtures/s02-meeting.md`，查看解析，重新解析，刷新 | 终态 100%，标题/行号/正文和表格可见；终态持久化 |
| 响应式 | 320/768/1024/1440 × 900 | 无横向溢出，单 h1；控制台 error/warn 空；键盘可达操作 |

自动测试覆盖 S01 权限回归、四格式位置、重复上传/投递、撤权后 Worker 拒绝执行和下载、失败重试不覆盖旧分块、重复 retry 不重复创建、取消中的旧执行无法发布、删除补偿及重新上传恢复、broker 失败不丢任务、租约过期恢复、自动重试上限、流式上传 413、非法作用域/扩展名/MIME/签名、长文本重叠与表格表头。

集成故障使用真实 PostgreSQL + 可注入存储/broker，实链路冒烟另使用真实 MinIO、Redis、Celery；不将故障注入描述为整机崩溃测试。测试只使用演示身份与自建样本，不修改真实客户资料。

保留浏览器样本文档 `1cac64ea-7a30-4d5f-800d-a54f3f453339`，其余 S02 实链路测试资料立即隐藏并异步清理；不提交 `.env`、凭据或原始上传文件到 Git。

## 边界与下一阶段

- S02 使用字符切分，token_count 空，未创建模型向量索引；S03 选择模型与 tokenizer 后重新评测切分并实现索引原子切换。
- PDF 无 OCR，复杂表格当前为文本块；DOCX 用正文块位置，不伪造页码。表格结构分片保真限 DOCX/Markdown。
- 本地 Worker 使用 solo 池，进程重启后由租约补偿；生产需独立资源隔离、硬超时、吞吐/内存与故障演练。未实施完整无障碍审计或真实生产 OIDC。
- S07 增加引用前需保留来源版本/快照，当前重新解析成功会替换旧分块，删除会清理原文件和分块。
- Python 输出包含第三方 Starlette/AnyIO/PyMuPDF 的弃用警告，无失败；没有为消除警告引入不相关依赖升级。

解析 API 参考：[PyMuPDF 文本定位](https://pymupdf.readthedocs.io/en/latest/recipes-text.html)、[python-docx 正文顺序](https://python-docx.readthedocs.io/en/latest/api/document.html)。
