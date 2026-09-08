# Solution Copilot 代码实现规格

> 状态：Draft 0.1
> 范围：MVP 业务与技术实现
> 上位说明：[AGENT.md](./AGENT.md)
> 本文不定义代码风格、Git 流程、发布流程等团队工程规范。

## 1. 文档目的

本文将 `AGENT.md` 中的产品目标转换为可以直接进入设计和开发的技术规格，明确：

- MVP 的系统边界与业务闭环。
- 前后端、Agent、检索、存储和异步任务的模块职责。
- 核心领域模型、状态机和接口契约。
- 数据隔离、事实引用、可观测性和错误处理要求。
- 功能验收标准与建议开发顺序。

除非在实施前形成新的架构决策记录，开发应以本文为默认实现依据。

## 2. MVP 成功定义

用户能够完成以下端到端流程：

1. 登录并进入所属组织。
2. 创建客户与方案项目。
3. 上传一份客户会议纪要或直接粘贴需求文本。
4. 系统解析材料并生成结构化需求档案。
5. 系统列出缺失信息和澄清问题。
6. 用户回答问题并确认需求档案。
7. 系统从知识库中检索相关产品资料和案例。
8. 系统生成带引用的方案大纲。
9. 用户确认大纲，系统分章节生成解决方案。
10. 用户编辑方案、保存版本并导出 DOCX 或 Markdown。

端到端演示不得依赖开发人员直接修改数据库或手工拼接中间结果。

## 3. 范围约束

### 3.1 MVP 包含

- 组织、用户、客户与项目管理。
- TXT、Markdown、PDF、DOCX 文档上传与解析。
- 结构化需求提取、补充、确认与版本更新。
- 项目级会话与流式回复。
- 公共知识、组织知识和客户私有知识的索引与检索。
- 关键词和向量混合检索。
- 带引用的大纲及方案章节生成。
- 方案编辑、版本保存、Markdown 与 DOCX 导出。
- 会话记忆、项目记忆和客户记忆的管理与重置。
- 异步任务进度、失败状态和安全重试。
- 基础运行指标与审计事件。

### 3.2 MVP 不包含

- 自动向外部联系人发送邮件或方案。
- 自动报价、合同生成、签约和 CRM 回写。
- 完整互联网自治调研 Agent。
- 多人实时协同编辑。
- PPT 文件自动排版。
- 企业级审批流与复杂角色自定义。
- 基于未经采集的数据宣称效率提升或业务成果。

## 4. 总体架构

```text
┌───────────────────────────────────────────────────────────────┐
│ Next.js Web                                                  │
│ 客户/项目工作台 · 文档上传 · 需求确认 · 对话 · 方案编辑器      │
└─────────────────────────────┬─────────────────────────────────┘
                              │ HTTPS / SSE
┌─────────────────────────────▼─────────────────────────────────┐
│ FastAPI Application                                          │
│ Auth · REST API · SSE · Application Services · Authorization │
└───────────────┬────────────────────┬──────────────────────────┘
                │                    │
┌───────────────▼──────────┐  ┌──────▼──────────────────────────┐
│ LangGraph Workflows      │  │ Background Workers             │
│ 提取/澄清/检索/生成/校验  │  │ 解析/索引/导出/长任务           │
└───────────────┬──────────┘  └──────┬──────────────────────────┘
                │                    │
┌───────────────▼────────────────────▼──────────────────────────┐
│ PostgreSQL + pgvector · Redis · S3-compatible Object Storage │
└───────────────────────────────────────────────────────────────┘
```

### 4.1 技术选型

| 区域 | 选型 | 说明 |
| --- | --- | --- |
| 前端 | Next.js、React、TypeScript | 使用 App Router 构建工作台 |
| UI | Tailwind CSS、shadcn/ui | 表单、对话框、表格和基础布局 |
| 服务端状态 | TanStack Query | 请求缓存、轮询、失效和乐观更新 |
| 本地交互状态 | Zustand | 编辑器和临时界面状态 |
| 编辑器 | Tiptap | 结构化方案编辑与选区操作 |
| API | FastAPI、Pydantic | REST、SSE、输入输出校验 |
| ORM/迁移 | SQLAlchemy、Alembic | 领域数据访问与数据库迁移 |
| Agent | LangGraph | 显式状态机、检查点和人在回路 |
| 数据库 | PostgreSQL、pgvector | 业务、全文索引和向量数据 |
| 队列 | Redis、Celery | 解析、索引、导出等异步任务 |
| 文件 | S3-compatible API | 本地使用 MinIO，部署环境可替换 |
| PDF/DOCX | PyMuPDF、python-docx | 文档解析和 DOCX 导出 |
| 追踪 | OpenTelemetry | API、任务和模型调用链路 |

具体版本在工程初始化时锁定，并记录在依赖清单中。模型、Embedding 和对象存储必须通过适配层接入。

### 4.2 运行环境基线

项目初始化时采用以下基线。这里固定兼容范围，精确补丁版本由锁文件记录：

| 组件 | 兼容范围 | 选择理由 |
| --- | --- | --- |
| Node.js | `24.x` LTS | 前端生产运行时；不使用处于 Current 阶段的版本 |
| pnpm | `10.x` | 管理前端依赖与 workspace |
| Python | `>=3.12,<3.14` | 兼顾类型能力与 AI、文档处理生态兼容性 |
| uv | 初始化时锁定 | 管理 Python 项目、依赖组和 `uv.lock` |
| PostgreSQL | `17.x` | 主数据库、全文检索和 pgvector 宿主 |
| pgvector | `>=0.8,<0.9` | 向量类型、余弦距离和 HNSW 索引 |
| Redis | `7.4.x` | Celery broker、短期缓存和限流状态 |
| MinIO | 固定 release tag 或镜像 digest | 本地 S3-compatible 对象存储 |

Node.js 生产环境只选择官方仍处于 LTS 支持期的主版本。Python 兼容范围在 `pyproject.toml` 中声明，开发、CI 和生产使用同一小版本系列。

### 4.3 前端依赖

#### MVP 运行时依赖

| 包 | 用途 | 使用约束 |
| --- | --- | --- |
| `next`、`react`、`react-dom` | Web 应用与渲染 | 使用 Next.js App Router |
| `@tanstack/react-query` | 服务端状态同步 | API 数据不得重复存入 Zustand |
| `zustand` | 编辑器和临时 UI 状态 | 不保存权威业务数据 |
| `zod` | 表单与客户端边界校验 | Schema 与 API 生成类型配合使用 |
| `react-hook-form`、`@hookform/resolvers` | 表单状态与校验 | 客户、项目、需求表单统一使用 |
| `@tiptap/react`、`@tiptap/core`、`@tiptap/starter-kit` | 方案富文本编辑 | 方案仍以结构化章节作为服务端权威数据 |
| `@tiptap/extension-link`、`@tiptap/extension-table`、`@tiptap/extension-placeholder` | 链接、表格和占位能力 | 仅按实际编辑功能启用扩展 |
| `next-auth` | OIDC 会话接入 | 服务端 API 仍需独立验证访问令牌 |
| `lucide-react` | 图标 | 禁止用 Emoji 代替产品操作图标 |
| `class-variance-authority`、`clsx`、`tailwind-merge` | 组件样式组合 | 配合本地 shadcn/ui 组件使用 |
| `sonner` | 非阻塞反馈 | 关键错误仍需在页面上下文显示 |
| `date-fns` | 时间展示 | API 时间统一按 UTC 传输 |

`shadcn/ui` 作为组件源码生成工具使用，不视为单一运行时依赖。Radix UI 包随实际采用的组件按需加入，避免一次安装全部组件依赖。

#### 前端开发与测试依赖

| 包 | 用途 |
| --- | --- |
| `typescript` | 静态类型检查 |
| `eslint`、`eslint-config-next` | Next.js 基础静态检查 |
| `vitest`、`jsdom` | 单元与组件测试运行环境 |
| `@testing-library/react`、`@testing-library/user-event`、`@testing-library/jest-dom` | 组件行为测试 |
| `@playwright/test` | 浏览器端到端测试 |
| `msw` | 前端 API mock 和异常场景测试 |
| `openapi-typescript` | 从后端 OpenAPI 生成客户端类型 |

是否采用 Prettier、额外 ESLint 规则和 CSS 检查工具，留待代码规范确定时决定。

### 4.4 后端依赖

#### API 与配置

| 包 | 用途 | 使用约束 |
| --- | --- | --- |
| `fastapi` | REST API、依赖注入和 OpenAPI | 路由层不直接实现领域逻辑 |
| `uvicorn[standard]` | ASGI 服务 | 生产部署参数由运行环境管理 |
| `pydantic`、`pydantic-settings` | 数据契约与配置 | 所有外部输入经过 Schema 校验 |
| `python-multipart` | 文件上传表单 | 只用于受限制的上传接口 |
| `orjson` | 高效 JSON 编解码 | 作为 API JSON 实现，不改变契约 |
| `httpx` | 异步 HTTP 客户端 | 外部调用统一配置超时和重试 |

#### 数据库与持久化

| 包 | 用途 | 使用约束 |
| --- | --- | --- |
| `sqlalchemy` | ORM、查询和事务 | 使用 SQLAlchemy 2.x 风格 API |
| `psycopg[binary,pool]` | PostgreSQL 异步驱动与连接池 | API、Worker 和检查点共享统一驱动生态 |
| `alembic` | Schema 迁移 | 生产环境禁止启动时自动改表 |
| `pgvector` | SQLAlchemy/Python 向量类型 | 向量维度由 Embedding 配置生成 |

#### Agent、模型与检索

| 包 | 用途 | 使用约束 |
| --- | --- | --- |
| `langgraph` | Agent 图和状态流转 | 节点保持单一职责 |
| `langgraph-checkpoint-postgres` | PostgreSQL 工作流检查点 | 检查点查询同样执行租户校验 |
| `langchain-core` | 消息、工具和模型基础接口 | 不在领域层暴露 LangChain 类型 |
| `openai` | 首个 OpenAI-compatible 模型适配器 | 封装在模型基础设施层，可被替换 |
| `tenacity` | 有界重试与退避 | 仅重试明确可重试错误 |
| `tiktoken` | OpenAI-compatible token 估算 | 其他供应商通过各自适配器实现 |
| `rapidfuzz` | 需求和检索结果近似去重 | 只能辅助匹配，不自动覆盖确认数据 |

只有接入新的模型供应商时才增加相应 SDK。禁止为了“可能以后使用”预装多个模型厂商依赖。

#### 任务、文件与导出

| 包 | 用途 | 使用约束 |
| --- | --- | --- |
| `celery[redis]` | 分布式异步任务 | 业务任务状态仍写入 `jobs` 表 |
| `redis` | 缓存和 Redis 客户端 | 不存放权威业务实体 |
| `boto3` | S3-compatible 对象存储 | 通过对象存储适配器封装 |
| `pymupdf` | PDF 文本和结构提取 | 对页数、解析时间和内存设限 |
| `python-docx` | DOCX 解析与生成 | 导出后执行可打开性验证 |
| `charset-normalizer` | 文本文档编码识别 | 无法可靠识别时要求用户确认 |

#### 安全与可观测性

| 包 | 用途 | 使用约束 |
| --- | --- | --- |
| `PyJWT[crypto]` | JWT/JWKS 验证 | 必须校验签名、发行方、受众和有效期 |
| `structlog` | 结构化应用日志 | 默认执行敏感字段过滤 |
| `opentelemetry-api`、`opentelemetry-sdk` | 统一追踪接口与 SDK | 不采集文档全文和完整 Prompt |
| `opentelemetry-instrumentation-fastapi` | FastAPI 自动追踪 | 与请求 ID 关联 |
| `opentelemetry-instrumentation-sqlalchemy` | 数据库调用追踪 | 不记录含私密正文的 SQL 参数 |
| `opentelemetry-exporter-otlp` | 导出 traces/metrics | 本地无接收端时允许关闭 |
| `prometheus-client` | 服务与 Worker 指标 | 标签不得包含高基数字段和敏感数据 |

### 4.5 后端开发、测试与评测依赖

这些依赖应放入 uv 的独立依赖组，不进入最小生产镜像：

| 依赖组 | 包 | 用途 |
| --- | --- | --- |
| `dev` | `ruff` | 基础 lint 和格式化能力；规则后续确定 |
| `dev` | `mypy` | 静态类型检查 |
| `test` | `pytest`、`pytest-asyncio` | 单元和异步测试 |
| `test` | `pytest-cov` | 覆盖率数据采集 |
| `test` | `respx` | 模型及外部 HTTP 调用 mock |
| `test` | `testcontainers[postgres,redis]` | PostgreSQL、pgvector 和 Redis 集成测试 |
| `test` | `freezegun` | 时间、过期和重试场景测试 |
| `eval` | `pandas` | 离线评测结果分析 |
| `eval` | `scikit-learn` | 基础检索与分类评测指标 |

如果 `testcontainers` 在 CI 环境不可用，应连接 CI 提供的临时服务，而不是把集成测试降级为只使用 SQLite。SQLite 不能替代 PostgreSQL 全文检索、pgvector、事务和隔离行为。

### 4.6 基础设施与系统依赖

| 服务/组件 | MVP 用途 | 要求 |
| --- | --- | --- |
| PostgreSQL + pgvector | 业务数据、检查点、全文与向量检索 | 启动迁移显式执行 `CREATE EXTENSION vector` |
| Redis | Celery broker、缓存和限流 | 不作为任务最终状态的唯一来源 |
| MinIO | 本地对象存储 | bucket 默认私有，使用签名访问 |
| OTLP Collector（可选） | 本地追踪接收 | 缺失时应用仍能正常运行 |

MVP 不引入 Elasticsearch、独立向量数据库、Kafka 或 Kubernetes。只有评测或容量数据证明 PostgreSQL/Redis 架构不足时才提交替换决策。

S00 实施说明（2026-09-06，D013）：本阶段仅安装 Web、配置、健康检查及队列探针实际使用依赖；4.3–4.5 是全 MVP 规划，其他包按阶段引入。开发启动命令见 README；当前不构建生产镜像。新增 `python-dotenv` 用于统一开发进程环境载入，S00 检查以 Ruff、pytest、TypeScript、Next build 和真实队列 smoke 为准。

### 4.7 依赖清单文件

初始化代码时创建且提交：

```text
package.json                 # 根脚本和 workspace 元数据
pnpm-workspace.yaml          # 前端/packages workspace
pnpm-lock.yaml               # 前端精确依赖版本
apps/web/package.json        # Web 直接依赖
pyproject.toml               # Python 兼容范围和直接依赖
uv.lock                      # Python 全平台精确解析结果
.python-version              # 本地 Python 小版本
.nvmrc 或 .node-version      # 本地 Node.js 主版本
infra/compose.yaml           # 基础设施镜像与服务配置
```

约束：

- 仓库只保留 `pnpm-lock.yaml`，不得同时提交 npm 或 Yarn 锁文件。
- Python 以 `pyproject.toml` + `uv.lock` 为权威来源，不再手工维护重复的 `requirements.txt`。
- `uv.lock` 和 `pnpm-lock.yaml` 必须提交版本控制，不得手工编辑。
- 容器镜像固定主次版本；生产发布进一步固定不可变 digest。
- 直接依赖必须能够说明业务用途，未被代码或构建流程使用的包应移除。
- 前端、API 和 Worker 的生产镜像只安装各自运行所需依赖。

### 4.8 可选依赖启用条件

以下依赖不进入初始 MVP，满足条件后再引入：

| 候选依赖 | 启用条件 |
| --- | --- |
| `langsmith` | 确认采用 LangSmith 托管追踪或评测 |
| `unstructured` | PyMuPDF/python-docx 无法满足复杂版面评测要求 |
| `playwright` Python 包 | MVP 纳入动态网页调研 |
| `trafilatura` | MVP 纳入公开网页正文提取 |
| `weasyprint` | 正式确认 PDF 导出且完成系统库评估 |
| `boto3-stubs` | 后端类型检查需要覆盖对象存储适配器 |
| 专用 reranker SDK | 混合检索评测表明基础融合结果不足 |
| 其他模型厂商 SDK | 确认接入对应厂商并完成数据合规评估 |

### 4.9 依赖更新策略

- 安全修复：确认影响后优先升级，完成相关单元、集成和端到端测试。
- 补丁版本：可按月批量更新，锁文件变更必须经过 CI。
- 次版本：阅读变更说明，重点回归 Agent 状态、ORM、编辑器和导出链路。
- 主版本：单独提交升级，记录迁移影响和回滚方案，不与业务功能混合。
- 模型或 Embedding 版本变化：视为行为依赖升级，必须运行 AI 评测集。
- PostgreSQL、pgvector、Redis 和对象存储升级：必须先验证备份恢复、迁移和回滚。
- 禁止 CI 在未修改声明文件时自动重写锁文件。

项目初始化后，依赖的实际版本和传递依赖以锁文件为准；`SPEC.md` 只维护兼容范围、直接依赖职责和治理原则。

## 5. 仓库模块建议

```text
SolutionEngineerAgent/
├── AGENT.md
├── SPEC.md
├── apps/
│   ├── web/                     # Next.js 前端
│   ├── api/                     # FastAPI HTTP/SSE 入口
│   └── worker/                  # Celery worker 启动入口
├── packages/
│   └── contracts/               # 可生成或共享的 API 类型定义
├── backend/
│   └── solution_copilot/
│       ├── domain/              # 领域实体、枚举、领域规则
│       ├── application/         # 用例与事务边界
│       ├── infrastructure/      # DB、对象存储、模型和队列适配器
│       ├── agents/              # LangGraph 图、节点和状态定义
│       ├── retrieval/           # 解析、切分、索引、检索和引用
│       ├── exports/             # Markdown/DOCX 导出
│       └── observability/       # 日志、指标和追踪
├── migrations/                  # Alembic migrations
├── prompts/                     # 版本化 Prompt 模板与输出 Schema
├── evals/                       # 检索及生成评测集
├── fixtures/                    # 演示用脱敏数据
└── infra/                       # Docker Compose 和本地基础设施
```

该结构是模块职责建议，不在本文规定文件命名、导入顺序等编码风格。

## 6. 身份认证与数据隔离

### 6.1 身份模型

- 所有受保护 API 必须获得可信身份，包含 `user_id` 和当前 `organization_id`。
- 生产环境通过 OIDC/JWT 接入；API 使用发行方 JWKS 验证签名、有效期和受众。
- 本地开发可启用显式的开发身份模式，但该模式必须默认关闭且不能用于生产。

### 6.2 最小角色

| 角色 | 能力 |
| --- | --- |
| `owner` | 管理组织、成员和全部组织数据 |
| `member` | 管理被授权的客户、项目和方案 |
| `viewer` | 只读访问被授权内容和导出文件 |

### 6.3 隔离规则

- 所有组织级实体必须包含 `organization_id`。
- 客户私有实体必须额外包含 `customer_id`；项目实体必须包含 `project_id`。
- 业务查询不得仅按资源主键查询，必须同时校验组织范围。
- 检索过滤条件必须在数据库查询阶段执行，不能在取得候选结果后才过滤。
- Agent 工具调用只能接收服务端注入的范围标识，不得信任模型生成的组织或客户 ID。
- 跨客户复制资料必须由用户显式操作，并生成审计事件。

## 7. 核心领域模型

所有表默认包含：

- `id: uuid`
- `created_at: timestamptz`
- `updated_at: timestamptz`
- 需要软删除的实体包含 `deleted_at: timestamptz | null`

### 7.1 组织与成员

#### `organizations`

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `name` | varchar(160) | 非空 |
| `slug` | varchar(80) | 全局唯一 |
| `settings` | jsonb | 非空，默认 `{}` |

#### `users`

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `external_subject` | varchar(255) | 唯一，OIDC subject |
| `email` | varchar(320) | 唯一 |
| `display_name` | varchar(160) | 非空 |

#### `memberships`

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `organization_id` | uuid | 外键，非空 |
| `user_id` | uuid | 外键，非空 |
| `role` | enum | `owner/member/viewer` |

唯一约束：`(organization_id, user_id)`。

### 7.2 客户与项目

#### `customers`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `organization_id` | uuid | 租户范围 |
| `name` | varchar(200) | 客户名称 |
| `industry` | varchar(120) | 行业 |
| `region` | varchar(120) | 地区 |
| `company_size` | varchar(80) | 企业规模描述 |
| `profile` | jsonb | 其他结构化背景 |

#### `projects`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `organization_id` | uuid | 租户范围 |
| `customer_id` | uuid | 所属客户 |
| `name` | varchar(200) | 项目名称 |
| `description` | text | 项目简介 |
| `status` | enum | 见项目状态机 |
| `owner_user_id` | uuid | 项目负责人 |
| `settings` | jsonb | 模板、语言等配置 |

项目状态：

```text
collecting → researching → drafting → reviewing → completed
     └──────────────→ archived ←────────────────────┘
```

业务状态变更必须由应用服务完成，不允许客户端任意写入状态值。

### 7.3 需求

#### `requirement_profiles`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `organization_id` | uuid | 租户范围 |
| `customer_id` | uuid | 客户范围 |
| `project_id` | uuid | 一对一关联项目 |
| `version` | integer | 乐观锁与历史追踪 |
| `summary` | text | 客户需求摘要 |
| `completeness_score` | numeric(5,2) | 0–100，仅用于引导 |
| `confirmed_at` | timestamptz | 用户确认时间 |
| `confirmed_by` | uuid | 确认用户 |

#### `requirement_items`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `profile_id` | uuid | 所属需求档案 |
| `category` | enum | 需求分类 |
| `title` | varchar(240) | 简短标题 |
| `content` | text | 规范化需求内容 |
| `priority` | enum | `must/should/could/unknown` |
| `status` | enum | `proposed/confirmed/rejected/conflicted` |
| `confidence` | numeric(4,3) | 0–1，模型提取置信度 |
| `source_type` | enum | `document/message/user/model` |
| `source_ref` | jsonb | 文档页码、消息 ID 等定位信息 |

需求分类至少包含：

- `background`
- `pain_point`
- `goal`
- `functional`
- `non_functional`
- `integration`
- `data`
- `security_compliance`
- `constraint`
- `timeline_budget`
- `acceptance_metric`
- `risk`

#### `clarifications`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `project_id` | uuid | 所属项目 |
| `question` | text | 澄清问题 |
| `reason` | text | 提问原因 |
| `importance` | enum | `required/recommended` |
| `status` | enum | `open/answered/skipped` |
| `answer` | text | 用户回答 |
| `answered_by` | uuid | 回答者 |
| `answered_at` | timestamptz | 回答时间 |

### 7.4 对话与记忆

#### `conversations`

- `organization_id`
- `customer_id`
- `project_id`
- `title`
- `status: active/closed`
- `last_message_at`

#### `messages`

- `conversation_id`
- `role: user/assistant/system/tool`
- `content: jsonb`
- `model_name: varchar | null`
- `prompt_version: varchar | null`
- `generation_run_id: uuid | null`

`content` 使用块结构，至少支持 `text`、`citation`、`tool_status` 和 `error`，避免将所有响应退化为单一字符串。

#### `memories`

- `organization_id`
- `customer_id: uuid | null`
- `project_id: uuid | null`
- `scope: conversation/project/customer`
- `kind: fact/preference/decision/constraint/summary`
- `content`
- `source_message_id: uuid | null`
- `status: proposed/confirmed/expired`
- `expires_at: timestamptz | null`

只有用户明确确认或系统规则允许的内容才能成为长期客户记忆。模型自行推断的内容默认保存为 `proposed`。

### 7.5 知识库

#### `documents`

- `organization_id`
- `customer_id: uuid | null`
- `project_id: uuid | null`
- `scope: public/organization/customer/project`
- `title`
- `source_type: upload/manual/generated`
- `mime_type`
- `storage_key`
- `sha256`
- `status: uploaded/parsing/parsed/indexing/ready/failed/disabled`（S02 解析完成为 parsed，S03 索引后为 ready）
- `metadata: jsonb`
- `error_code: varchar | null`
- `error_message: text | null`

同一组织内 `(sha256, scope, customer_id, project_id)` 可用于检测重复上传。

#### `document_chunks`

- `document_id`
- `organization_id`
- `customer_id: uuid | null`
- `project_id: uuid | null`
- `ordinal`
- `content`
- `token_count`（S02 留空；字符数与字符切分参数见 metadata，S03 接入真实 tokenizer）
- `page_number: integer | null`
- `section_path: jsonb`
- `embedding: vector`
- `search_vector: tsvector`
- `metadata: jsonb`

向量维度由所选 Embedding 模型决定，迁移时不得硬编码与模型不匹配的维度。

S02 实现补充（D015）：Chunk 客户/项目范围通过 document 联结；向量和全文索引列由 S03 引入。文档 generation 与分块 generation 原子切换，当前不保存历史引用。新增 `GET /documents/{id}/chunks`、`GET /documents/{id}/download`；reindex 在 S02 执行重新解析，S03 扩展索引。

### 7.6 方案与引用

#### `solution_templates`

- `organization_id: uuid | null`，为空代表系统模板
- `name`
- `description`
- `schema: jsonb`
- `version`
- `is_active`

#### `solutions`

- `organization_id`
- `customer_id`
- `project_id`
- `template_id`
- `title`
- `status: outlining/generating/draft/review/approved`
- `current_version_id: uuid | null`

#### `solution_versions`

- `solution_id`
- `version`
- `content: jsonb`
- `plain_markdown: text`
- `created_by`
- `generation_run_id: uuid | null`
- `change_summary`

`content` 至少包含有稳定 ID 的章节数组；编辑或重新生成单一章节时不得重建其他章节 ID。

#### `citations`

- `solution_version_id`
- `section_id`
- `claim_text`
- `source_type: document/research/user_input`
- `document_id: uuid | null`
- `chunk_id: uuid | null`
- `source_url: text | null`
- `locator: jsonb`，例如页码、章节和文本偏移
- `verification_status: supported/partial/unverified`

### 7.7 运行与审计

#### `generation_runs`

- `organization_id`
- `project_id`
- `run_type`
- `status: queued/running/waiting_user/succeeded/failed/cancelled`
- `model_provider`
- `model_name`
- `prompt_version`
- `input_tokens`、`output_tokens`
- `latency_ms`
- `estimated_cost`
- `error_code`、`error_message`
- `started_at`、`completed_at`

#### `jobs`

- `organization_id`
- `job_type`
- `resource_type`、`resource_id`
- `status: queued/running/succeeded/failed/cancelled`
- `progress: integer`
- `attempts`
- `error_code`、`error_message`

#### `audit_events`

- `organization_id`
- `actor_user_id: uuid | null`
- `action`
- `resource_type`、`resource_id`
- `metadata: jsonb`
- `occurred_at`

审计元数据不得记录完整 Prompt、文档正文、访问令牌或模型密钥。

## 8. 文档处理与索引

### 8.1 上传约束

- MVP 支持 `.txt`、`.md`、`.pdf`、`.docx`。
- 上传前后都要验证扩展名、MIME 类型和文件签名。
- 默认单文件大小上限建议为 25 MB，配置项可覆盖。
- 对象存储路径由服务端生成，不使用用户文件名作为真实存储键。
- 文件名只作为显示元数据保存。

### 8.2 处理管线

```text
upload
  → validate
  → store original
  → extract text and structure
  → normalize
  → chunk
  → create embeddings
  → create full-text index
  → mark ready
```

### 8.3 切分策略

- 优先按标题、段落、列表和表格等文档结构切分。
- 普通文本块建议为 500–800 tokens，重叠 80–120 tokens。
- 表格应整体保留；过长表格按行分片，同时保留表头。
- 每个分块保留页码、章节路径、文档 ID 和顺序号。
- 切分参数需写入文档元数据，以便索引重建和评测复现。

### 8.4 失败与重试

- 解析、Embedding 和索引是可重试的幂等任务。
- 相同文档版本重复执行不得产生重复有效分块。
- 达到最大重试次数后将文档标记为 `failed`，并向用户显示可操作错误。
- 重新索引创建新索引结果成功后，再切换并清理旧结果，避免半成品可见。

## 9. 检索规格

### 9.1 查询构建

检索输入由以下内容组成：

- 当前用户问题或待生成章节目标。
- 已确认的结构化需求。
- 当前客户与项目上下文。
- 用户选择的知识范围和文档标签。

模型可生成检索改写，但服务端必须保留原始查询，并限制改写数量和长度。

### 9.2 混合检索

1. 使用 PostgreSQL Full Text Search 获取关键词候选。
2. 使用 pgvector 获取语义候选。
3. 对两组候选使用 Reciprocal Rank Fusion 合并。
4. 按数据范围、启用状态、文档类型和标签过滤。
5. 去除高度重复分块。
6. 返回最终 Top K 以及完整来源元数据。

建议默认值：

- 两路各召回 20 条。
- 融合后返回 8 条。
- 单一文档默认最多占最终结果的 40%。

所有值均为可配置参数，最终以评测集结果为准。

S03 实现补充（D009）：本地 `BAAI/bge-small-zh-v1.5` 固定 revision，Embedding 为 512 维；tokenizer 分块上限 440、重叠 80。中文关键词使用 jieba 归一化后写入 PostgreSQL `simple` 全文索引。两路各取 20 条，以 RRF 融合后返回 8 条，单文档默认最多 40%。MVP 使用精确向量扫描；模型 profile 变化后必须重建索引，旧 profile 不参与新查询。30 条固定中文问题的真实链路结果保存在 `evals/s03-results.json`。

### 9.3 检索结果结构

```json
{
  "query": "客户需要满足哪些数据合规要求？",
  "items": [
    {
      "chunk_id": "uuid",
      "document_id": "uuid",
      "title": "数据安全产品说明",
      "content": "...",
      "page_number": 12,
      "section_path": ["安全能力", "数据隔离"],
      "score": 0.87,
      "scope": "organization"
    }
  ]
}
```

`score` 只用于内部排序和调试，不应展示为事实置信度。

## 10. Agent 工作流

### 10.1 状态结构

Agent 状态至少包含：

```python
class SolutionWorkflowState(TypedDict):
    organization_id: str
    customer_id: str
    project_id: str
    conversation_id: str
    run_id: str
    user_goal: str
    requirement_profile_id: str | None
    open_clarification_ids: list[str]
    retrieval_query: str | None
    retrieved_chunk_ids: list[str]
    solution_id: str | None
    target_section_id: str | None
    warnings: list[str]
    next_action: str | None
```

状态只保存引用和必要摘要；大文档正文通过受控工具按 ID 获取，避免检查点无限增长。

### 10.2 主图节点

```text
ingest_request
      ↓
extract_requirements
      ↓
validate_requirements
      ├── incomplete → generate_clarifications → wait_for_user
      │                                      ↑          │
      └──────────────────────────────────────┘          │
                                                       ↓
build_retrieval_queries → retrieve_evidence → draft_outline
                                              ↓
                                      wait_outline_approval
                                              ↓
                                      generate_sections
                                              ↓
                                        verify_solution
                                         ├── revise
                                         └── ready_for_review
```

### 10.3 节点职责

| 节点 | 输入 | 输出 | 关键限制 |
| --- | --- | --- | --- |
| `extract_requirements` | 文档/消息 | 需求项候选 | 必须输出 Schema；保留来源 |
| `validate_requirements` | 需求档案 | 缺口、冲突、完整度 | 分数不可替代人工确认 |
| `generate_clarifications` | 缺口 | 澄清问题 | 去重，区分必答与建议 |
| `build_retrieval_queries` | 需求、章节目标 | 检索查询 | 不接受模型提供租户范围 |
| `retrieve_evidence` | 查询、服务端范围 | 分块引用 | 仅返回授权范围资料 |
| `draft_outline` | 已确认需求、证据 | 章节大纲 | 大纲需人工确认 |
| `generate_sections` | 大纲、需求、证据 | 方案章节 | 主张必须关联引用或标记待核实 |
| `verify_solution` | 方案、需求、引用 | 问题清单与评分 | 检查覆盖、矛盾、越权和泄漏 |

### 10.4 人在回路

工作流必须在以下位置持久化检查点并暂停：

- 存在必答澄清问题。
- 大纲等待用户确认。
- 用户要求确认重要假设。
- 方案完成并等待最终评审。

恢复工作流时必须验证操作者仍具有对应项目权限。

### 10.5 模型输出约束

- 结构化步骤使用 Pydantic/JSON Schema 校验。
- Schema 校验失败可进行有限次数修复重试。
- Prompt 注入不得修改系统授权范围、工具能力和引用规则。
- 文档内容属于不可信输入；其中的指令不得被当作系统或用户命令执行。
- 工具参数必须经过类型、权限和资源归属校验。
- 生成温度、最大输出和超时由任务类型配置，不能由客户端任意覆盖。

## 11. 需求提取规格

### 11.1 输入

- 用户消息 ID 列表。
- 已解析文档 ID 列表。
- 现有需求档案，可为空。
- 提取语言，默认跟随项目语言。

### 11.2 输出

```json
{
  "summary": "客户希望建设统一的智能客服平台",
  "items": [
    {
      "category": "functional",
      "title": "多渠道会话接入",
      "content": "需要接入网站、微信和移动应用会话。",
      "priority": "must",
      "confidence": 0.92,
      "source": {
        "type": "document",
        "document_id": "uuid",
        "page_number": 3,
        "quote": "..."
      }
    }
  ],
  "conflicts": [],
  "missing_categories": ["acceptance_metric"]
}
```

### 11.3 合并规则

- 高相似度且不冲突的需求合并，并保留全部来源。
- 新信息与已确认需求冲突时，不自动覆盖；创建 `conflicted` 项并要求用户处理。
- 用户直接编辑或确认的信息优先级高于模型提取结果。
- 重新提取不得删除用户确认内容。

### 11.4 完整度

完整度用于辅助追问，按项目模板配置权重。默认必备类别：

- 客户背景
- 业务痛点
- 建设目标
- 核心功能
- 系统集成
- 安全与合规
- 约束条件
- 验收指标

完整度分数必须同时显示缺失项，不能只展示单一百分比。

## 12. 方案生成规格

### 12.1 默认章节

1. 执行摘要
2. 客户背景与现状
3. 需求与痛点分析
4. 建设目标
5. 总体解决方案
6. 功能设计
7. 技术架构
8. 系统集成与数据流
9. 安全与合规
10. 实施计划
11. 风险及应对措施
12. 验收指标
13. 预期价值
14. 参考资料

用户可在确认大纲阶段增加、删除和调整章节顺序。

### 12.2 内容规则

- 每个章节使用稳定 `section_id`。
- 章节生成应输入相关需求项和相关证据，不向模型塞入整个知识库。
- 事实性主张必须绑定引用；没有证据时标记“待客户确认”或“待进一步核实”。
- 产品能力不得超出已启用的产品资料。
- 预期价值可以给出计算方法，但没有基线数据时不得生成确定的提升百分比。
- 重新生成章节只创建新方案版本，不覆盖已有版本。

### 12.3 质量检查

最少检查：

- 已确认需求覆盖率。
- 必答澄清问题是否仍未回答。
- 章节之间是否存在明显矛盾。
- 事实性主张是否有引用。
- 引用是否属于当前授权范围。
- 是否出现其他客户名称或私有信息。
- 是否包含未被产品资料支持的能力承诺。
- 是否包含明确且可验证的验收指标。

质量检查结果应包含规则 ID、严重程度、章节 ID、说明和建议，不只返回一个总分。

## 13. API 规格

### 13.1 通用约定

- 基础路径：`/api/v1`。
- 请求和响应使用 JSON；文件上传使用 `multipart/form-data`。
- 列表采用游标分页：`limit`、`after`。
- 时间使用 ISO 8601 UTC。
- 写操作支持 `Idempotency-Key` 的接口必须在 API 文档中标记。
- 更新有版本的资源时提交 `version`；版本冲突返回 HTTP `409`。
- 长任务返回 `202 Accepted` 和 `job_id`。

### 13.2 错误结构

```json
{
  "error": {
    "code": "DOCUMENT_PARSE_FAILED",
    "message": "无法解析该文档。",
    "details": {},
    "request_id": "uuid"
  }
}
```

对外错误信息不得包含堆栈、SQL、模型密钥、内部 Prompt 或其他客户数据。

### 13.3 客户与项目

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/customers` | 创建客户 |
| `GET` | `/customers` | 客户列表 |
| `GET` | `/customers/{customer_id}` | 客户详情 |
| `PATCH` | `/customers/{customer_id}` | 更新客户 |
| `DELETE` | `/customers/{customer_id}` | 软删除客户 |
| `POST` | `/customers/{customer_id}/projects` | 创建项目 |
| `GET` | `/projects` | 项目列表 |
| `GET` | `/projects/{project_id}` | 项目详情 |
| `PATCH` | `/projects/{project_id}` | 更新项目 |
| `POST` | `/projects/{project_id}/archive` | 归档项目 |

### 13.4 文档与知识库

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/documents` | 上传文档，返回文档和任务 |
| `GET` | `/documents` | 按范围、状态、标签查询 |
| `GET` | `/documents/{document_id}` | 文档详情和处理状态 |
| `POST` | `/documents/{document_id}/reindex` | 重新索引 |
| `POST` | `/documents/{document_id}/disable` | 停止参与检索 |
| `DELETE` | `/documents/{document_id}` | 删除文档及索引数据 |
| `POST` | `/retrieval/search` | 调试或人工检索 |

上传请求必须包含 `scope`。当 `scope` 为 `customer` 或 `project` 时，相应 ID 必须存在并属于当前组织。

### 13.5 需求

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/projects/{project_id}/requirements/extractions` | 发起提取任务 |
| `GET` | `/projects/{project_id}/requirements` | 获取需求档案 |
| `PATCH` | `/projects/{project_id}/requirements` | 编辑需求档案 |
| `POST` | `/projects/{project_id}/requirements/confirm` | 确认需求 |
| `GET` | `/projects/{project_id}/clarifications` | 获取澄清问题 |
| `POST` | `/clarifications/{id}/answer` | 回答问题 |
| `POST` | `/clarifications/{id}/skip` | 跳过建议问题 |

### 13.6 对话与 Agent

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/projects/{project_id}/conversations` | 创建会话 |
| `GET` | `/conversations/{conversation_id}/messages` | 获取历史消息 |
| `POST` | `/conversations/{conversation_id}/messages` | 发送消息并启动运行 |
| `GET` | `/runs/{run_id}/events` | SSE 获取运行事件 |
| `POST` | `/runs/{run_id}/resume` | 提交人工输入并恢复 |
| `POST` | `/runs/{run_id}/cancel` | 取消运行 |

SSE 事件至少包括：

- `run.started`
- `node.started`
- `message.delta`
- `citation.created`
- `run.waiting_user`
- `run.completed`
- `run.failed`

流式断线后，客户端可使用最后事件 ID 重连；最终数据以持久化消息和运行状态为准。

### 13.7 方案与导出

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/projects/{project_id}/solutions` | 创建方案 |
| `POST` | `/solutions/{solution_id}/outline` | 生成大纲 |
| `POST` | `/solutions/{solution_id}/outline/approve` | 确认大纲 |
| `POST` | `/solutions/{solution_id}/sections/{section_id}/generate` | 生成或重生成章节 |
| `GET` | `/solutions/{solution_id}` | 获取当前版本 |
| `PATCH` | `/solutions/{solution_id}` | 保存人工编辑版本 |
| `GET` | `/solutions/{solution_id}/versions` | 获取版本列表 |
| `POST` | `/solutions/{solution_id}/verify` | 执行质量检查 |
| `POST` | `/solutions/{solution_id}/exports` | 发起导出任务 |
| `GET` | `/exports/{export_id}/download` | 获取短时效下载地址 |

### 13.8 记忆

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/projects/{project_id}/memories` | 查看项目相关记忆 |
| `PATCH` | `/memories/{memory_id}` | 确认或修改记忆 |
| `DELETE` | `/memories/{memory_id}` | 删除单条记忆 |
| `POST` | `/conversations/{id}/reset` | 重置会话上下文 |
| `POST` | `/projects/{id}/memories/reset` | 重置项目记忆 |

重置接口必须返回预估影响数量并要求显式 `confirm=true`；客户级记忆不能被项目级重置删除。

### 13.9 任务状态

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/jobs/{job_id}` | 查询任务状态与进度 |
| `POST` | `/jobs/{job_id}/retry` | 重试允许重试的失败任务 |
| `POST` | `/jobs/{job_id}/cancel` | 取消未完成任务 |

## 14. 前端页面规格

### 14.1 页面路由

```text
/login
/customers
/customers/[customerId]
/projects
/projects/[projectId]/overview
/projects/[projectId]/requirements
/projects/[projectId]/knowledge
/projects/[projectId]/chat
/projects/[projectId]/solution
/projects/[projectId]/history
/knowledge
/settings/memories
```

### 14.2 项目工作台

项目详情使用统一工作台框架：

- 顶部显示客户、项目状态和负责人。
- 左侧为业务导航。
- 主区域展示当前任务。
- 右侧可折叠面板展示来源、运行进度和警告。

### 14.3 需求页面

- 按类别分组展示需求项。
- 支持新增、编辑、确认、拒绝和解决冲突。
- 展示来源定位与模型置信度，但不暗示置信度等同真实性。
- 同时展示完整度和具体缺失项。
- 澄清问题可逐项回答或跳过建议问题。

### 14.4 对话页面

- 支持流式响应和运行步骤摘要。
- 引用使用编号或引用卡片展示，可打开来源定位。
- `waiting_user` 状态显示明确的待确认操作。
- 页面刷新或断线后能够恢复运行状态。
- 用户取消运行后，已持久化的消息和运行记录仍可查看。

### 14.5 方案页面

- 左侧显示大纲和章节状态。
- 中间为 Tiptap 编辑器。
- 右侧展示当前段落引用、质量问题和 AI 操作。
- 支持保存版本、生成单章、重新生成单章和全篇质量检查。
- 导出操作显示异步进度，完成后提供下载。

## 15. 模型与 Prompt 适配层

### 15.1 接口

业务层只依赖以下抽象能力：

```python
class ChatModel(Protocol):
    async def invoke(self, request: ChatRequest) -> ChatResponse: ...
    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatEvent]: ...

class EmbeddingModel(Protocol):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...
```

供应商 SDK、重试、速率限制和错误映射位于基础设施适配器中。

### 15.2 Prompt 管理

- Prompt 文件放在 `prompts/`，具备稳定名称和语义版本。
- 每次生成记录 Prompt 版本、模型和参数摘要。
- Prompt 变更必须能够通过固定评测集回归。
- Prompt 中不得嵌入生产密钥、客户原文或不可审计的远程内容。
- 系统指令、用户输入、检索证据必须用明确边界分隔。

### 15.3 降级策略

- 模型超时或限流时进行有上限的指数退避重试。
- 结构化输出失败时允许一次格式修复，仍失败则返回明确错误。
- 部分章节生成失败时保留已完成章节，不回滚整个方案。
- Embedding 服务不可用时可保留文档为 `indexing` 或 `failed`，不能错误标记为 `ready`。

## 16. 导出规格

### 16.1 Markdown

- 保留标题层级、列表、表格、代码块和引用编号。
- 文末生成参考资料列表。
- 未验证内容保留醒目标记。

### 16.2 DOCX

- 应用统一标题、正文、列表、表格和页眉页脚样式。
- 自动生成目录所需的标题层级。
- 引用编号与参考资料一致。
- 文件生成后执行可打开性检查；失败不得提供下载链接。

### 16.3 下载安全

- 导出文件存储在项目范围路径。
- 下载前再次执行权限校验。
- 使用短时效签名 URL 或由 API 流式代理下载。
- 下载日志只记录元数据，不记录文件正文。

## 17. 异步任务与幂等性

适合异步执行的任务：

- 文档解析与索引。
- 大批量 Embedding。
- 需求提取。
- 大纲与多章节生成。
- 方案质量检查。
- DOCX/PDF 导出。

要求：

- 每个任务具有业务幂等键。
- Worker 开始前重新验证资源状态与组织归属。
- 任务进度写入 `jobs`，前端不得依赖 Celery 内部任务格式。
- 取消采用协作式取消：节点间检查取消状态。
- Worker 重启后不得把旧任务永久留在 `running`。

## 18. 可观测性与指标

### 18.1 结构化日志字段

- `request_id`
- `trace_id`
- `organization_id`
- `user_id`
- `project_id`
- `run_id`
- `job_id`
- `event`
- `duration_ms`
- `error_code`

不得记录：访问令牌、密钥、完整上传文档、完整 Prompt、完整模型响应和跨租户标识组合。

### 18.2 系统指标

- API 请求量、延迟和错误率。
- 队列长度、等待时间和失败次数。
- 文档解析成功率和索引耗时。
- 检索延迟、空结果率和用户引用打开率。
- 模型调用延迟、token、成本、重试和 Schema 失败率。
- Agent 节点耗时、暂停次数和恢复成功率。

### 18.3 产品指标

- 从项目创建到首份方案的耗时。
- 每份方案人工编辑次数和版本数量。
- 已确认需求覆盖率。
- 有引用事实占比和未验证主张数量。
- 导出成功率。
- 用户主动采用、修改或删除生成章节的比例。

效率提升需要与明确基线对比，不能仅由生成数量推断。

## 19. 安全与隐私基线

- 密钥仅通过服务端密钥管理或环境注入，不进入仓库、日志或前端包。
- 上传文件不可直接公开访问。
- 对文件类型、大小、页数和解析耗时设置限制。
- 对用户文本和上传文档执行 Prompt 注入防护：内容只作为数据，不作为高优先级指令。
- 所有删除、重置、跨客户复制和导出行为写入审计事件。
- 模型供应商是否保留数据必须可配置并向部署方说明。
- 在模型调用前按组织策略执行敏感信息处理。
- 所有数据库备份与对象存储使用加密传输；生产存储启用静态加密。

## 20. 非功能要求

### 20.1 性能目标

- 普通 CRUD API 的服务端 P95 小于 500 ms，不含网络和第三方服务延迟。
- 检索 API 的服务端 P95 小于 2 s，基于 MVP 规模评测集。
- 发送消息后 2 s 内返回运行已启动或首个流式事件。
- 长任务必须展示进度或当前阶段，不能让前端无限等待。

### 20.2 可靠性

- 业务写操作使用数据库事务。
- 方案版本、需求确认和记忆更新支持乐观锁。
- 工作流检查点允许服务重启后恢复。
- 第三方模型失败不得破坏已确认需求或已保存方案版本。

### 20.3 可维护性

- 领域层不直接依赖 Web 框架、模型 SDK、Celery 或对象存储 SDK。
- Agent 节点尽量保持单一职责，外部副作用通过应用服务执行。
- 外部供应商错误映射为稳定的内部错误码。
- 核心业务状态使用显式枚举和状态迁移，避免散落字符串判断。

## 21. 测试与评测范围

本文只定义需要验证什么，具体测试框架和覆盖率规范后续维护。

### 21.1 单元测试重点

- 项目状态迁移。
- 需求合并与冲突规则。
- 客户/项目范围过滤构建。
- 混合检索融合与去重。
- 引用完整性检查。
- 记忆作用域和重置规则。
- 方案版本并发更新。

### 21.2 集成测试重点

- 文档上传到可检索的完整管线。
- PostgreSQL 全文检索与 pgvector 检索。
- Worker 重试、幂等和失败恢复。
- Agent 暂停、检查点保存和恢复。
- 导出文件生成与权限校验。
- 不同组织、客户之间的访问与检索隔离。

### 21.3 端到端测试重点

- 从客户创建到方案导出的完整 MVP 流程。
- 页面刷新后恢复生成任务。
- 需求冲突由用户确认后继续生成。
- 重新生成单章不覆盖其他章节。
- 文档解析失败后用户能够重试或更换文件。

### 21.4 AI 评测集

至少准备一套脱敏演示数据，包含：

- 3 份客户会议纪要。
- 1 份包含矛盾信息的需求材料。
- 10–20 份产品资料和历史案例。
- 30 条带标准相关文档的检索问题。
- 需求提取的人工标注结果。
- 方案必须覆盖的需求与禁止承诺清单。

评测至少测量：检索命中率、需求提取准确性、需求覆盖率、引用支持率和敏感信息泄漏。

## 22. MVP 验收标准

### 22.1 客户与项目

- 用户只能访问所属组织授权的数据。
- 客户和项目可创建、更新、查询和归档。
- 已归档项目默认不出现在活动列表中，但可恢复查看。

### 22.2 文档与检索

- 四种支持格式能够上传并显示明确处理状态。
- 文档解析失败有可理解的错误和重试入口。
- 可在公共、组织、客户、项目范围中正确过滤检索。
- 检索结果能够定位到原文档及页码或章节。

### 22.3 需求

- 系统能够生成结构化需求项并保留来源。
- 用户编辑和确认的需求不会被后续提取静默覆盖。
- 缺失信息能够转化为可回答的澄清问题。
- 冲突需求必须由用户处理后才能视为已确认。

### 22.4 Agent 与方案

- 工作流可以在澄清和大纲确认处暂停、刷新页面并恢复。
- 方案按已确认大纲生成，支持单章重新生成。
- 事实性内容展示引用或待核实标记。
- 质量检查可以定位到具体章节和问题。
- 不同客户的资料不会出现在错误项目的检索与方案中。

### 22.5 导出与历史

- 用户可以保存至少两个方案版本并查看版本元数据。
- Markdown 与 DOCX 导出可成功打开且章节顺序正确。
- 导出引用与方案引用一致。
- 无权限用户不能下载文件，即使获得旧下载地址。

## 23. 建议开发阶段

以下为高层里程碑。具体执行拆为 S00–S09，阶段负责人、状态、验收与交接统一维护在 [STATUS.md](./STATUS.md)，协同规则见 [PROJECT_BRIEF.md](./PROJECT_BRIEF.md)。

### 阶段 0：工程骨架

- 初始化 Web、API、Worker 和基础设施。
- 接通 PostgreSQL、pgvector、Redis、MinIO。
- 建立认证上下文、迁移和统一错误结构。

### 阶段 1：客户、项目与文档

- 完成客户/项目 CRUD 和权限过滤。
- 完成上传、解析、对象存储、任务状态和索引。
- 提供检索调试页面，先验证知识链路。

### 阶段 2：结构化需求

- 完成需求 Schema、提取、合并、冲突和追问。
- 完成需求确认页面。
- 建立第一版提取评测集。

### 阶段 3：Agent 与方案

- 实现 LangGraph 主工作流、检查点与 SSE。
- 完成大纲确认、分章生成、引用和版本保存。
- 增加基础质量检查。

### 阶段 4：导出与验证

- 完成 Markdown、DOCX 导出。
- 完成端到端、隔离、失败恢复和基础性能测试。
- 准备脱敏演示项目和可复现指标。

## 24. 待决策事项

下列事项及实现契约的补充问题统一追踪在 [DECISIONS.md](./DECISIONS.md)；架构关系见 [ARCHITECTURE.md](./ARCHITECTURE.md)。未决项不代表所有前置工作均需暂停，按台账中的解决阶段推进。

实施前需要通过简短架构决策记录确认：

1. OIDC 身份提供方及本地开发身份方案。
2. 首个模型供应商、模型能力和数据保留设置。
3. Embedding 模型及向量维度。
4. PostgreSQL 是否启用行级安全作为应用层过滤的第二道防线。
5. Celery 消息格式和任务结果的持久化策略。
6. 首个演示行业与相应方案模板。
7. DOCX 样式模板和品牌要求。
8. MVP 是否包含 PDF 导出。

这些事项未决定时，应保持接口可替换，不应把供应商细节扩散到领域层。


## 25. S01 实施补充（2026-09-07，D014）

- `users.dev_token_hash` 为仅开发使用的可空唯一 SHA-256 摘要字段；`customer_access` 以 organization/customer/user 三元组授权，组合外键关联客户和成员。
- Customer/Project 增加整型 `version`（初始 1），使用 SQLAlchemy version_id_col；所有 PATCH/归档需携带当前 version。PATCH 保留省略字段，不允许修改组织、客户归属、负责人或项目状态。
- 客户归档使用既有 DELETE 软删除路径，返回归档后的客户；旗下项目停止创建/修改，保留读取；项目 archived 只读。列表返回 `{items,next_cursor}`，以 UUID 升序游标分页，`archived` 选择归档范围。
- S01 owner 创建客户，owner/member 可管理授权内数据，viewer 只读；组织/成员/授权本阶段通过受控 seed/数据库配置，暂不提供管理页面。
- `/api/v1/me` 返回当前用户与所属组织/角色；JWT/JWKS 验证已实现，真实 OIDC 供应商和 Web 授权码登录流程待部署前接入，当前 token 登录仅作为可运行入口。
- Web 新增查询/表单运行依赖 TanStack Query、react-hook-form、@hookform/resolvers、zod；Prettier 为格式检查开发依赖。状态页及业务页沿用语义 CSS tokens；Tailwind/shadcn 在需要具体业务组件时引入。
- S01 项目总览只展示已实现的资料与负责人，不提供未实现的需求/知识/对话操作；后续阶段补齐 14.2 工作台侧栏和来源面板。
