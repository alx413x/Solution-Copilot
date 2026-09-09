# S06 Agent 编排验收

- 日期：2026-09-10；输入 `4d47871`，main；状态：done；实现整合 `a327040`，本地验收通过。
- 范围：LangGraph 原生 PostgreSQL 检查点、需求确认和大纲确认、恢复/取消、编排面板、Run/SSE 复用。
- 迁移：`f68db74e19a0`，四张原生 checkpoint 表；已应用，Alembic check 无差异。

## 自动验证

- `RUN_DB_TESTS=1 .venv/bin/pytest -q`：34 passed，真实 PostgreSQL 随机 schema；已有第三方弃用警告 6 条。`tests/test_s06.py` 单独运行 3 passed。
- S06 测试覆盖两次中断、请求重放、只读/跨组织拒绝和原生 checkpoint；独立进程在检查点写入后、事务提交前 `os._exit(19)`，消息与检查点回滚，新 Python 进程恢复后仅一条助手消息。
- 实际检索 SQL 配合确定向量验证：gate1 恢复排队后档案变化、gate2 排队后档案变化、资料停用、Embedding profile 失效及客户授权撤销均拒绝继续；取消与会话重置后旧 Worker 不发布。
- Ruff、前端类型、Prettier 和 `pnpm build` 通过。业务测试不使用 SQLite。
- `alembic current` 为 `f68db74e19a0 (head)`；`alembic check` 无新操作。

## 真实链路与浏览器

- `scripts/smoke_s06.py` 通过真实 Web→API→dispatcher→Celery→PostgreSQL 链路完成两个确认门、8 项澄清回答、需求确认和 SSE，耗时 34.93 秒。保留项目 `71087696-d28d-47aa-8ca3-175b8c3637d1`、会话 `5421ea9f-62be-42fa-8974-c6697b0a132c`。
- 浏览器以已有完整需求完成新编排启动、gate2 大纲展示、确认及刷新后保持完成；轮询后只显示一个编排面板。320/768/1024/1440 无横向溢出且只有一个 `h1`；键盘 Tab 从确认按钮移动到取消按钮时显示实线焦点，移动端排版已核对。gate1 补全和取消/重置由 HTTP 真实链路及自动测试覆盖。

## 实施边界

- S04/S05 继续负责提取与明确澄清回答。编排 Worker 在进入图前复用需求完整度/确认规则与 S03 授权检索，图负责需求门、大纲节点与大纲门。
- 大纲是稳定 ID 的固定 14 章模板，完成状态 `ready_for_generation` 表示等待 S07；不声称生成了方案正文。暂无证据时明确显示警告。
- 原生 PostgresSaver 共用 SQLAlchemy 底层 psycopg 连接，`durability="sync"`；每次从一个确认点推进到下一个确认点作为同一事务，包含 checkpoint、Run、事件和消息。崩溃从上一个已提交确认点重做纯图节点，未提交消息不会残留。
- 本阶段只有本地检索与纯图节点，在短事务内持有项目锁。S07 接外部模型时必须拆出事务并加入结果版本校验，不能把远程调用放进当前锁区。
- API 与 Worker 都重新校验身份；scope 从项目推导。恢复令牌使用 Run ID + gate + request UUID，不开放任意 thread_id/checkpoint_id 或状态注入。请求重放返回已保存结果，不能跨门二次推进。
- 每项目只允许一个等待/活动编排；等待时可继续 S05 对话。取消后重开用于修改大纲；S07 再接大纲编辑、方案版本和历史引用快照。
- 检查点不对浏览器暴露；持有引用 ID/索引代次及档案版本，不保存完整文档。当前没有检查点清理策略，生产前制定保留期。

## 未验证与后续边界

生产 OIDC、完整 axe/屏幕阅读器审计和独立浏览器控制台日志审计未执行；S07 正文生成不在本阶段。检查点清理策略在生产部署前确定。
