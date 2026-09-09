# Solution Copilot

面向售前工程师的可追溯方案工作台。当前已实现 S00–S03 基础与检索，以及 S04 需求结构化、S05 澄清与对话；下一阶段为 S06 Agent 编排。

## 本地启动

前置：Node 24、pnpm（项目自动选择 packageManager 指定的版本）、Python 3.12、uv 0.8.19、已运行的 Docker Desktop/Compose。所有命令在仓库根目录执行。

```sh
cp .env.example .env  # 首次执行；已有配置不要覆盖
pnpm install --frozen-lockfile
uv sync --frozen --group test
docker compose --env-file .env -f infra/compose.yaml up -d --wait
uv run python scripts/init_infra.py
uv run alembic upgrade head
uv run python -m scripts.prepare_embeddings  # 首次下载固定版本的本地检索模型
DEV_AUTH_ENABLED=true uv run python scripts/seed_s01.py  # 首次生成本地演示身份
DEV_AUTH_ENABLED=true uv run python scripts/dev.py
```

访问 [登录页](http://127.0.0.1:3000/login)，使用 `.local/demo-credentials.json` 中 `a-owner` 的 token；也可使用 member/viewer 验证只读或客户范围。该文件权限为 0600，已排除 Git。重复启动直接使用已有凭据，不重复 seed。

访问 [工作台](http://127.0.0.1:3000/customers)、[组织资料](http://127.0.0.1:3000/knowledge)、[API 文档](http://127.0.0.1:8000/docs)。`dev.py` 同时启动 Web/API/Worker/dispatcher，任一退出会停止其他进程；Ctrl+C 关闭应用。Compose 保持运行，可用下列命令停止，保留数据卷：

```sh
docker compose --env-file .env -f infra/compose.yaml down
```

`.env.example` 仅包含本地演示凭据和空模型配置，`.env` 已排除版本控制。本地端口仅绑定回环地址。初始化脚本显式启用 pgvector、幂等创建私有 bucket，不在 API 启动时改数据库。S01 使用 Alembic 显式迁移业务表；应用启动不会自动改表。

## 验证

```sh
uv run ruff check apps backend scripts tests
uv run ruff format --check apps backend scripts tests
RUN_DB_TESTS=1 uv run --group test pytest -q
pnpm contracts
pnpm check
pnpm format:check
pnpm build
# 应用和基础设施运行时：
uv run --group test python scripts/smoke.py
uv run --group test python scripts/smoke_s01.py
uv run --group test python -m scripts.smoke_s02
uv run python -m scripts.eval_s03
uv run --group test python -m scripts.smoke_s04
```

`/api/v1/health/live` 只检查 API 存活；`/api/v1/health/ready` 检查数据库及 vector 扩展、Redis、私有 bucket，可用为 200，不可用为 503，响应不包含异常或凭据。浏览器通过同源 `/api/health` 调用 API，API 地址只在 Web 服务端读取。

smoke 会向真实 Celery Worker 投递探针，验证 Worker 连接三项基础设施；再验证对象上传、读取和匿名访问被拒，最终清除探针对象。探针结果使用短暂 RPC 回传；S02 业务任务结果与入队补偿保存在 PostgreSQL jobs。

## 文件与开发约定

- `apps/web`：Next.js App Router，S00 使用原生 CSS；业务组件按阶段接入 Tailwind/shadcn。
- `apps/api`、`apps/worker`：HTTP 与队列入口，共用 `backend/solution_copilot`。
- `packages/contracts`：从 FastAPI OpenAPI 自动生成的 JSON/TypeScript；接口改动运行 `pnpm contracts`，不手改生成文件。
- `infra/compose.yaml`：PostgreSQL/pgvector、Redis、MinIO；固定版本标签，仅用于本地开发。
- `tests`、`scripts`：失败路径测试、开发启动和集成验证。

Python 使用 Ruff 检查和格式化；前端使用 TypeScript strict。精确依赖版本以 `uv.lock`、`pnpm-lock.yaml` 为准，未用到的模型/编辑器/解析器依赖不预装。依赖基线、变更及交接见 [SPEC](SPEC.md)、[DECISIONS](DECISIONS.md)、[STATUS](STATUS.md)。

S03 只在本机调用固定版本的 Embedding 模型，不包含托管生成模型调用或生产部署镜像。MinIO 使用已发布的固定社区镜像（AGPLv3）；生产对象存储选型与镜像维护需在部署前重新评估，当前 S3 接口保持可替换。

本机代理或中断后残留进程问题、实际验收证据和已知限制见 [S00 验收记录](docs/S00_VALIDATION.md)。进行生产构建时建议先停止开发服务，构建后再启动。


## S01 身份与数据契约

- `DEV_AUTH_ENABLED` 默认 false，必须显式开启本地演示。`APP_ENV=production` 与开发身份同时配置会拒绝启动。开发凭据只用于演示；生产配置 `OIDC_ISSUER`、`OIDC_AUDIENCE`、`OIDC_JWKS_URL`，API 固定 RS256 并校验签名与必需声明。真实供应商与登录跳转尚未联调；现阶段登录页接收管理员提供的访问 token。
- API Bearer token 确认用户，`X-Organization-ID` 选择当前组织，服务端必须核验 Membership。owner 可创建客户和管理全组织，member 管理已授权客户/项目，viewer 仅查看。成员、授权与生产用户当前由受控数据库配置或本地 seed 建立；没有开放自助注册或成员管理页面。
- Web 把凭据保存在 HttpOnly / SameSite=Strict 会话 cookie，退出即清除；生产 cookie 使用 Secure。`WEB_ORIGIN` 默认 `http://127.0.0.1:3000`，用于写请求来源检查，部署必须设置实际公开 origin；不要用任意来源通配符。
- PATCH 仅更新提交字段，未知字段和显式 null 拒绝。修改及归档必须携带 `version`，冲突返回 409。项目 status 不接受客户端直接写入，归档使用专门端点。客户归档使用 DELETE 软删除，旗下项目保留可读、停止编辑，默认列表隐藏，可在“已归档”查看。
- seed 包含两个组织，每组织两个客户及 owner/member/viewer 三角色；member/viewer 仅客户 1 有授权。新建客户默认仅 owner 可访问，授权表 `customer_access` 需由管理侧配置。数据库组合外键确保客户/负责人属于同组织，当前不启用 RLS。
- `RUN_DB_TESTS=1` 在随机 PostgreSQL schema 中实际迁移、回滚并测试，最后只删除该测试 schema；不使用 SQLite，不清空开发表。未设置该变量时集成测试明确 skip。
- 详细验收与待完善事项见 [S01 验收记录](docs/S01_VALIDATION.md)。

`pnpm check` 先运行 `next typegen`，首次检出不依赖历史 `.next` 目录；Next 自动生成的 `next-env.d.ts` 不纳入版本控制。

## S02 文档处理

- 从组织资料、客户档案或项目总览进入资料页。支持 UTF-8 TXT/Markdown、文本 PDF、DOCX；上传默认 25 MiB，`UPLOAD_MAX_BYTES` 可配置（最大 100 MiB，Web 与 API 使用相同配置）。扫描 PDF 请先 OCR。
- 组织资料仅 owner 可写，成员可读；客户/项目资料沿用客户授权，viewer 与归档档案只读。暂不开放 public 跨组织知识。
- 上传异步返回 document/job；页面每 3 秒刷新状态，可查看带章节、行号、页码或正文块序号的片段，失败可重试，处理可取消，解析完成后可重新解析。重复文件按组织与作用域去重。
- `parsed` 表示解析完成；真实 tokenizer 分块、向量与关键词索引成功后标记 `ready`。索引失败会保留上一完整 generation，并提供重建入口。
- 原文件由每请求鉴权代理下载；停用立即禁止下载/分块读取，重新上传同内容可恢复。删除立即隐藏，dispatcher 持续补偿对象与分块清理。
- 必须同时运行 dispatcher（`uv run python -m scripts.dispatch_jobs`）；它补偿入队失败、丢失投递和过期 Worker 租约。业务状态只读取 jobs，不能用 Celery RPC 结果替代。默认租约 300 秒、最多 3 次自动尝试；重试新建 generation，旧执行不能覆盖新结果。
- 样本见 `docs/fixtures/s02-meeting.md`，验收及边界见 [S02 验收记录](docs/S02_VALIDATION.md)。

## S03 知识检索

S03 使用本地 `BAAI/bge-small-zh-v1.5`（512 维）和 jieba 建立 PostgreSQL pgvector/全文双路索引。授权范围在两路候选生成前应用，结果经 RRF 融合、去重并保留原文定位。首次启动先运行 `uv run python -m scripts.prepare_embeddings`；运行期只读本地模型。30 条中文问题的 Hit@8 为 100%，MRR@8 为 0.901，HTTP P95 为 23.65 ms，详见 [S03 验收记录](docs/S03_VALIDATION.md)。

DeepSeek 生成配置从根目录 `.env` 读取 `MODEL_PROVIDER`、`MODEL_NAME` 和 `MODEL_API_KEY`；`MODEL_BASE_URL` 可选，默认使用 `.env.example` 中的官方地址。密钥只填入本地 `.env`，不提交、不粘贴到聊天。S04 已接入生成调用，与 S03 的本地 Embedding 分开。

## S04 需求档案

从项目总览进入“需求档案”，可输入会议纪要或选择组织/当前客户/当前项目的已解析资料，提交异步提取任务。所选内容与既有需求将发送到配置的 DeepSeek 服务；页面说明这一行为。需保持 Worker 和 dispatcher 运行，首次更新运行 `uv run alembic upgrade head` 并重启服务。

按类别核对需求和来源，支持手动新增、编辑、确认、拒绝。新信息与旧项冲突时，显式选择保留原项或采用新项，解决所有冲突后才能确认整个档案。提取不会覆盖人工内容；期间有人编辑时结果停止发布，可重新提取。失败、取消和进程恢复均从数据库读取状态。

单次输入最多 30000 字、10 份资料和 200 个片段，每个档案最多 200 项。完整度只表示八类需求的覆盖情况，具体缺失项始终可见。真实合成样例验证运行 `uv run --group test python -m scripts.smoke_s04`，会调用配置的模型并保留演示项目；验收证据和边界见 [S04 验收记录](docs/S04_VALIDATION.md)。


## S05 澄清与对话

在项目总览进入“澄清与对话”，新建会话后发送需求，或点击“检查缺失信息”逐项回答。回答形成待确认需求，可从需求档案跳回原始消息；必答问题不可跳过，模型候选仍需核实。

消息可“保存为记忆”，选择会话、项目或客户范围；保存后点击“编辑 / 确认”才用于后续模型上下文。会话重置仅移出旧消息上下文并停用会话记忆；项目重置仅停用项目记忆，均先显示影响数量，客户记忆保留，需求档案不清空。

SSE 支持断线按事件 ID 重连，历史消息和运行状态来自 PostgreSQL；当前模型返回完整 JSON 后分段发布，不是逐 token 实时输出。保持 dispatcher 和 Worker 运行。生产运行恢复图留给 S06。

验收：`RUN_DB_TESTS=1 uv run --group test pytest -q`；`uv run --group test python scripts/smoke_s05.py` 使用本地演示账号和合成输入，创建保留的验收项目，调用已配置 DeepSeek。范围、指标与限制见 [S05 验收记录](docs/S05_VALIDATION.md)。
