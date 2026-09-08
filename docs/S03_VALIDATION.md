# S03 检索实现与待验收项

输入 `499f2ca`，main；状态 in_progress，尚未通过完整阶段验收。

已实现：Chunk 增加 pgvector/tsvector/模型 profile 和 GIN 索引；jieba 中文归一化；组织/客户/项目范围在两路 SQL 候选生成前限定；精确向量检索、RRF、近重复去除、单文档结果占比；资料页检索与来源下载；索引完整生成后原子替换，失败保留原有已发布分块。

实际验证：`RUN_DB_TESTS=1 .venv/bin/python -m pytest -q` 为 25 passed；Ruff check、Alembic upgrade/check 通过；OpenAPI/TypeScript 已生成，`next typegen` 和 `tsc --noEmit` 通过。回归测试对模型输出使用注入替身；S03 SQL 测试使用固定向量，仅验证授权、过滤、排名与版本行为，不能证明语义质量。

生产构建 `next build` 通过。未完成：真实 Embedding 推理、中文质量/延迟评测和浏览器实链路验收。`evals/s03-corpus.json` 含十份合成资料、三十个问题；`python -m scripts.eval_s03` 将记录 Hit@8、MRR@8、热模型 HTTP P95。没有运行时不得宣称达标。

用户选择 DeepSeek。查阅的 [DeepSeek 官方 API](https://api-docs.deepseek.com/api/deepseek-api/) 未列 Embedding 接口，已询问“DeepSeek 生成 + 本地向量化”组合；向量模型仍待回复。当前候选适配器为 FastEmbed + BAAI/bge-small-zh-v1.5（512 维），权重尚未下载；不代表用户已选定。

若确认本地模型：先执行 `uv run python -m scripts.prepare_embeddings`，固定 revision 下载至被忽略的 `.local/embedding`，再重启应用运行真实评测。运行期间 local_files_only，不发送文档到模型托管网站。实际 tokenizer 将片段限制为 440 tokens、重叠 80，保留来源位置及字符偏移。profile 变化后必须重建，旧模型向量不参与新模型检索。

精确向量检索针对 MVP 规模，性能不足后再评估 HNSW。未引入独立向量数据库、reranker、查询改写或新的任务系统。
