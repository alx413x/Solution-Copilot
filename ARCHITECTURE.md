# Solution Copilot 架构总览

更新日期：2026-09-09。状态：S00–S04 已实现；澄清对话及后续业务流程仍为设计基线。

## 架构定位

采用共享 Python 业务包的模块化服务设计，Web、API、Worker 分别运行。Agent 负责编排已有用例，领域规则与权限校验保持在业务服务中。

技术来源为 [SPEC.md](./SPEC.md) 第 4 节；决策依据见 [DECISIONS.md](./DECISIONS.md)。本文维护跨模块关系，精确字段和包清单继续集中在 SPEC。

## 组件与责任

| 组件                  | 责任                                         | 不应承担                             |
| --------------------- | -------------------------------------------- | ------------------------------------ |
| Next.js Web           | 客户/项目工作台、需求确认、对话、方案编辑    | 数据库直连、服务端密钥或最终权限判定 |
| FastAPI               | 身份校验、REST/SSE、应用用例及任务提交       | 在 HTTP 请求中长时间解析文档         |
| Python 应用/领域层    | 资源归属、需求合并、状态迁移、版本规则       | 依赖 UI 或供应商专有对象             |
| Celery Worker         | 解析、索引、生成、校验、导出等长任务执行     | 依赖请求进程的内存会话               |
| LangGraph             | 显式流程、暂停、检查点、恢复                 | 自行扩大用户授权范围                 |
| PostgreSQL + pgvector | 业务数据、任务状态、检查点、关键词及向量索引 | 保存原始大文件                       |
| Redis                 | 任务 broker、短期缓存、限流                  | 充当业务与任务结果唯一存储           |
| S3-compatible 存储    | 原始文档、导出文件                           | 默认公开访问客户文件                 |
| 模型适配器            | Chat/Embedding、超时、输出校验和调用记录     | 决定组织或客户访问范围               |

默认选型为 Tiptap、SQLAlchemy/Alembic、Celery、MinIO、OpenTelemetry；这些是既有 SPEC 基线，具体版本和供应商仍按初始化验证结果锁定。

## 数据流

```text
Web ──REST/SSE──> FastAPI ──应用服务──> PostgreSQL
                       │
                       └──任务提交──> Redis ──> Worker
                                                ├── 文档解析/索引
                                                ├── LangGraph → 模型适配器
                                                └── 导出 → 对象存储
Worker ──进度/结果/检查点──> PostgreSQL ──API──> Web
```

S02 将业务记录与 jobs 意图先提交 PostgreSQL，独立 dispatcher 再投递 Redis，并定期补偿未领取任务。jobs 同时充当 outbox；Worker 以文档 ID + generation、attempt 与租约进行幂等和执行隔离。结果与分块在同一事务中提交，终态独立于 Celery 结果后端。

### 导入与检索

上传与鉴权 → 文件验证与私有存储 → 文档记录/任务 → 解析 → 带页码或章节的分块 → Embedding/关键词索引 → ready。

S03 在解析后使用固定版本的本地 BGE tokenizer/Embedding 建立 pgvector 与中文全文索引，完整 generation 原子发布后进入 `ready`。上传先保存原文件的 DB 意图，再写对象；PUT 中断后任务读取并校验 SHA256，可恢复已成功但响应丢失的写入。删除先 tombstone 隐藏，再由 dispatcher 重试清理。API 与 Worker 共用作用域校验，Worker 在开始、检查点与发布前重新查询成员和客户授权。

检索在两路召回前应用同一授权范围，再融合、去重并返回来源。SPEC 第 9.2 节后续过滤用于进一步缩小候选，不得代替召回前权限过滤。

中文关键词检索使用 jieba 归一化后写入 PostgreSQL `simple` 配置，和 512 维语义召回通过 RRF 融合；30 条中文问题已完成实链路评测。MVP 使用精确向量扫描，规模增长并出现性能证据后再增加 HNSW。扫描 PDF/OCR 不在当前明确承诺内，遇到无文本文件需给出明确提示。

### 需求与方案

文档/用户消息 → Schema 校验的需求候选 → 合并与冲突检查 → 澄清/人工确认 → 检索证据 → 大纲确认 → 分章生成 → 质量检查 → 人工编辑 → 不可变版本 → 导出。

S04/S05 先实现可单独测试的提取、澄清和对话用例，S06 再用 LangGraph 编排；工作流暂停时保存检查点后释放 Worker，用户输入触发恢复任务。

S04 使用 requirement_profiles 的项目级 JSONB 档案与 requirement_extractions 的持久化输入/租约记录，复用现有 Worker/dispatcher。DeepSeek JSON 返回经字段、引用和关联校验后，在重新授权、来源 generation 和档案 version 一致时原子发布。人工编辑、确认及冲突解决共享同一项目写锁；引用保存最小摘录与定位。详细上限和后续拆表条件见 D016。

## 跨阶段契约

| 契约                  | 建立阶段 | 后续消费者              | 验证重点                       |
| --------------------- | -------- | ----------------------- | ------------------------------ |
| 身份上下文、资源归属  | S01      | 全部 API、Worker、Agent | tenant/customer/project 一致性 |
| 文档与 Chunk 来源定位 | S02      | S03/S04/S07/S08         | 原始来源可定位、索引版本明确   |
| 检索 Evidence 结构    | S03      | 需求辅助、方案引用      | 授权过滤、来源 ID、可复现候选  |
| 需求项及档案版本      | S04      | S05/S06/S07             | 用户确认优先、冲突不覆盖       |
| Run/消息/SSE 事件     | S05      | S06/Web                 | 事件重连、终态读取、取消       |
| 持久化工作流状态      | S06      | 生成与评审              | 暂停、重启、重复恢复幂等       |
| 章节、方案版本及引用  | S07      | S08                     | 稳定章节 ID、版本一致          |

API 以 FastAPI OpenAPI 为实现契约，前端生成类型；SPEC 第 13 节描述业务意图。接口变更由生产者与消费者共同验证。

## 存储与安全边界

- 关系主线：Organization → Customer → Project → Requirements/Conversations/Solutions；文档通过显式 scope 关联。
- tenant ID 来自已验证身份，不能由客户端或模型决定。子表通过父实体归属或冗余字段校验隔离。
- S02 不开放 `public`；组织知识所有成员可读、仅 owner 可写，客户/项目知识沿用 S01 显式客户授权。
- 长期记忆仅保存可追溯事实，模型推断默认 proposed；会话、项目、客户的删除范围分开。
- 引用绑定方案版本和来源快照。文档删除后哪些历史证据保留由 D010 明确。
- S02 原文件采用每请求即时鉴权代理下载和 no-store；S08 导出沿用该权限边界。

## 运行与验证

本地 Compose 基础设施和 Web/API/Worker 已验证；Alembic 已创建 S01 业务表、S02 文档任务表和 S03 pgvector/FTS 列。共享 application/access.py 负责授权范围；API 每次重新验证身份和成员，检索在候选生成前复用该范围。数据库组合外键加固组织一致性，尚未启用 RLS。Web 同源代理使用 HttpOnly cookie，写请求检查配置的 WEB_ORIGIN；生产 OIDC 真实供应商联调待完成。启动与各阶段证据见 README 和 `docs/*_VALIDATION.md`。

每阶段检查自己的故障恢复和数据隔离。S09 统一运行完整演示、中文检索评测、跨客户隔离、工作流重启与导出检查。具体指标见 SPEC 第 18–22 节。

尚未解决的选择集中记录在 DECISIONS，不能通过本总览暗示数据库、模型接口、部署或认证已经可用。
