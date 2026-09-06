# Solution Copilot

面向售前工程师的可追溯方案工作台。当前交付 S00：Next.js Web、FastAPI API、Celery Worker 及本地基础设施。业务功能从 S01 开始。

## 本地启动

前置：Node 24、pnpm（项目自动选择 packageManager 指定的 10.x）、Python 3.12、uv 0.8.19、已运行的 Docker Desktop/Compose。所有命令在仓库根目录执行。

```sh
cp .env.example .env  # 首次执行；已有配置不要覆盖
pnpm install --frozen-lockfile
uv sync --frozen --group test
docker compose --env-file .env -f infra/compose.yaml up -d --wait
uv run python scripts/init_infra.py
uv run python scripts/dev.py
```

访问 [工作台](http://127.0.0.1:3000)、[API 文档](http://127.0.0.1:8000/docs)。`dev.py` 同时启动 Web/API/Worker，任一退出会停止其他进程；Ctrl+C 关闭应用。Compose 保持运行，可用下列命令停止，保留数据卷：

```sh
docker compose --env-file .env -f infra/compose.yaml down
```

`.env.example` 仅包含本地演示凭据和空模型配置，`.env` 已排除版本控制。本地端口仅绑定回环地址。初始化脚本显式启用 pgvector、幂等创建私有 bucket，不在 API 启动时改数据库。S01 引入 Alembic 业务迁移。

## 验证

```sh
uv run ruff check apps backend scripts tests
uv run ruff format --check apps backend scripts tests
uv run --group test pytest -q
pnpm contracts
pnpm check
pnpm build
# 应用和基础设施运行时：
uv run --group test python scripts/smoke.py
```

`/api/v1/health/live` 只检查 API 存活；`/api/v1/health/ready` 检查数据库及 vector 扩展、Redis、私有 bucket，可用为 200，不可用为 503，响应不包含异常或凭据。浏览器通过同源 `/api/health` 调用 API，API 地址只在 Web 服务端读取。

smoke 会向真实 Celery Worker 投递探针，验证 Worker 连接三项基础设施；再验证对象上传、读取和匿名访问被拒，最终清除探针对象。探针结果使用短暂 RPC 回传，业务任务表、入队补偿和持久化结果在 S02 实现。

## 文件与开发约定

- `apps/web`：Next.js App Router，S00 使用原生 CSS；业务组件按阶段接入 Tailwind/shadcn。
- `apps/api`、`apps/worker`：HTTP 与队列入口，共用 `backend/solution_copilot`。
- `packages/contracts`：从 FastAPI OpenAPI 自动生成的 JSON/TypeScript；接口改动运行 `pnpm contracts`，不手改生成文件。
- `infra/compose.yaml`：PostgreSQL/pgvector、Redis、MinIO；固定版本标签，仅用于本地开发。
- `tests`、`scripts`：失败路径测试、开发启动和集成验证。

Python 使用 Ruff 检查和格式化；前端使用 TypeScript strict。精确依赖版本以 `uv.lock`、`pnpm-lock.yaml` 为准，未用到的模型/编辑器/解析器依赖不预装。依赖基线、变更及交接见 [SPEC](SPEC.md)、[DECISIONS](DECISIONS.md)、[STATUS](STATUS.md)。

本阶段不包含认证、客户 CRUD、模型调用、业务迁移或生产部署镜像。MinIO 使用已发布的固定社区镜像（AGPLv3）；生产对象存储选型与镜像维护需在部署前重新评估，当前 S3 接口保持可替换。

本机代理或中断后残留进程问题、实际验收证据和已知限制见 [S00 验收记录](docs/S00_VALIDATION.md)。进行生产构建时建议先停止开发服务，构建后再启动。
