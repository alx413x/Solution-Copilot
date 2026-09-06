# S00 验收记录

日期：2026-09-06。工作区：`/Users/deyi/Documents/ChatGPT/SolutionEngineerAgent`，分支 `main`，尚无 Git 提交。本记录对应当前未提交工作区。

## 范围与结果

S00 工程骨架验收通过，状态为 `review`（工作区交付；待版本归档整合）。S01–S09 未实施。

| 验收项 | 命令 / 方法 | 结果 |
| --- | --- | --- |
| Python 依赖 | `uv sync --group test` | 真实解析与安装；生成 uv.lock |
| Web 依赖 | `pnpm install` | pnpm 10.33.4 安装完成；生成 pnpm-lock.yaml |
| 基础设施 | `docker compose --env-file .env -f infra/compose.yaml up -d --wait` | PostgreSQL/pgvector、Redis、MinIO 三项 Healthy |
| 显式初始化 | `uv run python scripts/init_infra.py` | vector 扩展、私有 bucket 就绪；重复运行成功 |
| API 类型 | `pnpm contracts` | OpenAPI JSON 与 TypeScript 已生成 |
| 前端类型 | `pnpm check` | 通过；验收发现相对路径错误，修复后通过 |
| 前端生产构建 | `pnpm build` | Next.js 构建、TypeScript、静态生成全部通过；包含 `/`、`/_not-found`、`/api/health` |
| Python 静态检查 | `uv run ruff check apps backend scripts tests` 与 `ruff format --check` | 通过 |
| API 失败路径测试 | `uv run --group test pytest -q` | 3 passed：存活不依赖基础设施、就绪成功、失败 503 且不泄露凭据 |
| 真实集成 | `uv run --group test python scripts/smoke.py` | Web→API、API/Worker→PostgreSQL/vector、Redis、S3；真实排队任务执行成功 |
| 私有存储 | smoke 上传/读取/匿名请求/清理 | 内容一致、匿名返回 403、探针对象清理 |
| 浏览器正常态 | Codex 浏览器访问 `http://127.0.0.1:3000` | 中文状态页、三服务已连接；正常态未捕获 console error/warn |
| 加载与交互 | 点击和键盘 Enter 触发重新检查 | 检查中按钮禁用，随后展示结果；状态使用 aria-live |
| 响应式 | 320px 截图，768/1024/1440px DOM 测量 | 移动布局可读；后三尺寸 scrollWidth 等于 viewport width，无横向溢出 |
| 真实故障与恢复 | 停止 Redis、刷新页面，再 `up -d --wait redis` | API 503、仅 redis unavailable；页面显示任务队列未连接；恢复后复验 |

## 本机问题与处理

- Docker 原先未启动；经授权启动 Docker Desktop，拉取固定标签镜像并通过健康检查。
- 全局代理变量含无协议地址 `127.0.0.1:7897`，pnpm 版本切换出现 registry fetch/signature verification 失败。安装与验收命令临时清除代理变量后成功；没有禁用签名校验或修改全局代理。若复现，使用：

```sh
env -u ALL_PROXY -u HTTPS_PROXY -u HTTP_PROXY -u all_proxy -u https_proxy -u http_proxy pnpm install --frozen-lockfile
```

同样的临时前缀适用于 `pnpm contracts`、`pnpm check`、`pnpm build`。

- 任务中断后旧进程仍在，不能重复启动占用端口。读取 PID 和命令确认归属后停止旧开发主管进程并重启。曾出现旧 Web 请求超时，干净重启后恢复；不认定为已证实的业务缺陷。
- smoke 的固定回环 HTTP 请求使用 `trust_env=False`，避免本机代理影响本地验收。
- boto3 客户端不支持上下文管理协议，改为 `contextlib.closing` 确保关闭。

## 已知限制

- pytest 有两项上游弃用警告（Starlette httpx TestClient 与 anyio BlockingPortal），测试仍通过；后续升级测试依赖时处理。
- 只验证本机 macOS/ARM64 + Python 3.12/Node 24；锁文件不等同于已验证其他平台。没有生产部署、CI、应用镜像验收。
- 未执行完整 axe 自动审计或独立读屏软件测试；已检查语义结构、文字状态、焦点样式、键盘操作与指定宽度布局。
- 本地 MinIO 使用固定社区镜像，生产镜像维护、许可证及对象存储供应商需重新评估。
- 没有业务身份、数据隔离、业务表、持久化任务或模型调用；这些属于后续阶段，不能据此宣称 MVP 完成。
