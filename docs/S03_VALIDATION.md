# S03 知识检索验收记录

日期：2026-09-09。输入 `499f2ca`，实现提交 `656f0e6`，分支 main。S03 验收通过。

## 实现范围

- 文档解析后由同一 durable job 生成真实 token 分块、Embedding 和中文全文索引，完整生成后原子替换旧索引并标记 `ready`。
- 本地 `BAAI/bge-small-zh-v1.5` 固定 revision `46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59`，512 维；权重缓存在被忽略的 `.local/embedding`，运行时 `local_files_only`，资料不发送到模型托管网站。
- profile 为 `BAAI/bge-small-zh-v1.5:46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59:jieba-0.42.1:440-80-v1`。模型、分词或切分参数变化时，旧 profile 不参与检索，文档需重建索引。
- PostgreSQL 在组织/客户/项目授权范围内分别生成 pgvector 与 `tsvector` 候选，再用 RRF 融合、近重复去除和单文档占比限制返回 Top 8；结果保留文档、章节、页码/行号和下载来源。
- 资料页提供中文检索、来源入口和语义/关键词排名调试信息。

## 自动验证

```text
uv run python -m scripts.prepare_embeddings
→ Local encoder ready: 512 dimensions; revision 46fbe35...

RUN_DB_TESTS=1 uv run --group test pytest -q
→ 25 passed

./node_modules/.bin/next typegen
./node_modules/.bin/tsc --noEmit
./node_modules/.bin/next build
→ route types、TypeScript、生产构建通过

uv run python -m scripts.eval_s03
→ 30 questions; Hit@8 1.000; MRR@8 0.9011; warm HTTP P95 23.65 ms
```

完整逐题结果保存在 `evals/s03-results.json`。十份合成中文资料从 HTTP 上传，经 MinIO、dispatcher、Celery、本地模型和 PostgreSQL 真实入库；评测结束后脚本删除临时资料。P95 低于 SPEC 的 2 秒 MVP 目标。

数据库集成测试使用真实 PostgreSQL/pgvector/FTS，覆盖：候选生成前的组织与客户授权限制、未授权客户 404、撤销授权立即生效、停用文档退出检索、作用域/标签/MIME 过滤、旧 profile 隔离、失败重建保留上一完整 generation、融合与去重。固定测试向量只用于可重复验证 SQL 行为，质量指标来自上面的真实模型评测。

## 浏览器验收

在 `http://127.0.0.1:3000/knowledge` 使用本地 owner 身份完成：

1. 对 S02 留存的 `s02-meeting.md` 执行“重建索引”，终态从“解析完成”变为“可检索”。
2. 查询“客户希望如何访问系统？”，首条命中该文档，显示“示例客户会议纪要 / 业务需求 · 行 6–7”及原文“通过单点登录访问系统”。
3. 来源下载链接指向鉴权代理；调试信息显示语义排名 1、关键词排名 1、generation 3。
4. 页面只有一个 h1，表单可用键盘操作，控制台无 error/warn。

## 已知边界

- 当前评测是 10 份合成资料、30 个固定问题，证明本地 MVP 基线，不代表生产语料质量；S09 使用脱敏演示集复测。
- MVP 使用 PostgreSQL 精确向量扫描；数据量导致 P95 接近目标时再增加 HNSW。未加入独立向量库、reranker 或查询改写。
- DeepSeek 配置供 S04 生成使用，S03 不调用其接口；生成模型可用性、数据处理策略和费用尚未验收。
- OCR、复杂 PDF 表格保真、历史引用快照、生产 OIDC/部署和完整屏幕阅读器审计仍在后续阶段。
