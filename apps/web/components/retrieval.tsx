"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../lib/client";
import type { components } from "../../../packages/contracts/api";

export function Retrieval({
  customerId,
  projectId,
}: {
  customerId?: string;
  projectId?: string;
}) {
  const [query, setQuery] = useState("");
  const search = useMutation({
    mutationFn: () =>
      api<components["schemas"]["SearchResult"]>(
        "/api/backend/retrieval/search",
        "POST",
        { query, customer_id: customerId, project_id: projectId },
      ),
  });
  return (
    <div className="panel">
      <h2>检索资料</h2>
      <p className="muted">
        {projectId
          ? "检索本项目、所属客户及组织资料。"
          : customerId
            ? "检索本客户及组织资料。"
            : "检索组织资料。客户和项目资料请进入对应档案检索。"}
      </p>
      <form
        className="record-form"
        onSubmit={(event) => {
          event.preventDefault();
          search.mutate();
        }}
      >
        <label>
          检索问题
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            maxLength={500}
            required
            placeholder="例如：如何实现单点登录？"
          />
        </label>
        <div>
          <button
            className="primary"
            disabled={search.isPending || !query.trim()}
          >
            {search.isPending ? "正在检索…" : "检索"}
          </button>
        </div>
      </form>
      {search.error && (
        <p role="alert" className="error">
          {search.error.message}
        </p>
      )}
      {search.data && (
        <div aria-live="polite">
          <p>
            “{search.data.query}” · 找到 {search.data.items.length} 个片段
            {search.data.items.length === 0
              ? "，请检查资料是否已完成索引，或调整问题。"
              : ""}
          </p>
          {search.data.items.map((item) => (
            <article className="chunk" key={item.chunk_id}>
              <h3>{item.title}</h3>
              <p className="muted">
                {item.page_number ? `第 ${item.page_number} 页 · ` : ""}
                {item.section_path.join(" / ")}
                {typeof item.metadata.line_start === "number"
                  ? ` · 行 ${item.metadata.line_start}–${item.metadata.line_end}`
                  : ""}
              </p>
              <p className="description">{item.content}</p>
              <a href={`/api/backend/documents/${item.document_id}/download`}>
                下载来源原文
              </a>
              <details>
                <summary>检索调试信息</summary>
                <p>融合排序分数：{item.score.toFixed(4)}（不表示事实置信度）</p>
                <p>
                  语义排名：{item.ranks.semantic ?? "未命中"}；关键词排名：
                  {item.ranks.keyword ?? "未命中"}；版本：{item.generation}
                </p>
              </details>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
