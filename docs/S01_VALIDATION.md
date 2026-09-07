# S01 验收记录

日期：2026-09-07。输入提交 `61bdd0f`，工作区 `/Users/deyi/Documents/ChatGPT/SolutionEngineerAgent`，分支 main。已验收代码归档为 `2203ad2`（feat: implement S01 customer and project management），本次文档提交仅更新归档状态。

## 交付

- SQLAlchemy 组织、用户、成员、客户授权、客户、项目模型，Alembic 迁移 `6af8fd8a7f97`。
- API Bearer 开发 token / JWT-JWKS 验证、当前组织成员检查、共享授权范围服务；开发身份默认关闭，生产禁止启用。
- 客户/项目列表、详情、创建、PATCH、归档；UUID 游标分页、软归档、乐观锁与组合外键。
- Web 登录/退出、同源代理与 CSRF Origin 校验、客户/项目页面、表单校验与角色对应操作入口。
- OpenAPI/TypeScript 契约、随机开发凭据 seed、真实会话 smoke、PostgreSQL 集成测试、启动说明。

## 验收证据

| 项目 | 命令 / 方法 | 结果 |
| --- | --- | --- |
| 依赖解析 | uv add / pnpm add，锁文件自动生成 | 实际安装 SQLAlchemy/Alembic/PyJWT、Query/表单校验、Prettier |
| 开发库迁移 | `uv run alembic upgrade head` | 六张业务表已创建 |
| 迁移一致性 | `uv run alembic check` | No new upgrade operations detected |
| 迁移往返 | PostgreSQL 随机 schema 内 upgrade→downgrade→upgrade | 表正确建立/移除/重建 |
| 后端测试 | `RUN_DB_TESTS=1 uv run --group test pytest -q` | 12 passed；两项继承 S00 的上游弃用警告 |
| 静态与格式 | Ruff check / format --check；pnpm check / format:check | 通过 |
| API 契约 | `pnpm contracts` | 客户/项目及版本字段生成，无手改类型 |
| 前端构建 | `pnpm build` | Next.js 生产构建及静态生成通过 |
| 会话真实链路 | `uv run --group test python scripts/smoke_s01.py` | Origin 拒绝、HttpOnly/SameSite、组织选择越权、CRUD/归档、退出后 401 均通过 |
| S00 回归 | `uv run --group test python scripts/smoke.py` | Web→API、真实 Worker→基础设施、对象上传/读取/匿名拒绝通过 |
| 浏览器 CRUD | 本地 owner 登录，创建客户与项目，编辑背景和简介，分别确认归档 | 列表与详情实时更新；归档后只读，停止编辑/新建 |
| 浏览器布局 | 320/768/1024/1440px | 无横向溢出，详情仅一个 h1，表单标签与自动聚焦可见；未捕获 console error/warn |

测试覆盖：匿名/伪造凭据、组织成员验证、两组织数据隔离、同组织两客户授权差异、member/viewer 读写与项目归档边界、授权撤销后身份重验、未知字段/空名称/null 拒绝、部分 PATCH 保留原字段、版本冲突、真实双 Session 并发写入、跨组织组合外键拒绝、父客户归档限制、分页不重复、JWT 错误签名/issuer/audience/过期/缺失 exp、开发模式默认关闭和生产拒绝。

浏览器演示记录保留在本地数据库，均已归档：客户 `936b33d3-9c15-4808-9729-d4d0738c880f`，项目 `cea77372-9553-4ffd-bdb3-9414080ac1aa`。自动 smoke 也保留归档记录，脚本输出对应 ID，不写入客户真实数据。

## 已解决问题

- 第一版 PostgreSQL 测试 schema search_path 包含 public，导致 Alembic 版本标记回退到 public。现已改为仅测试 schema；确认开发 public 只有 alembic_version 后移除测试标记，再执行正式迁移。测试只删除随机命名的自身 schema，不清空开发数据。
- Next Route Handler 的内部 URL origin 与外部访问 origin 不一致，正常登录曾被拒。现按显式 `WEB_ORIGIN` 比较；正常/恶意来源均经过真实 HTTP 测试。
- PATCH 改为只更新提交字段；客户父行锁与组织/客户授权过滤一起执行，归档与项目写入串行；保留数据库版本检查。
- 补充负责人显示，修正客户详情中嵌套项目列表的标题层级，格式化前端源码。

## 限制与下一阶段

- JWT 校验使用本地生成 RSA 密钥模拟供应商完成安全测试；没有实际 OIDC 账号/授权码登录联调。生产提供方、用户开户流程须部署前完成，不能视为已验证生产登录。
- 组织/成员/客户授权暂无管理 UI/API，通过受控数据库配置或本地 seed 建立；新客户默认仅 owner 可见。未启用 RLS，依赖统一应用授权与数据库组合外键。
- S01 未增加访问客户资料的业务 Worker 任务；共享 resolve_identity/get_customer/get_project 已提供且测试，S02 在实际任务执行时重新验证，不得复用客户端提供的角色或旧授权。
- 只在当前 macOS/ARM64 + PostgreSQL 17 开发环境验收；无生产镜像、CI、完整 axe/独立读屏软件认证。
- 原有两项 Starlette/anyio 弃用警告未影响结果。导入、检索、Agent、导出仍属后续阶段。
