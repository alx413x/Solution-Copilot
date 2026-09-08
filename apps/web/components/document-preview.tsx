"use client";
import { useInfiniteQuery } from "@tanstack/react-query";
import { api, Chunk } from "../lib/client";

export function DocumentPreview({ id }: { id: string }) {
  const query = useInfiniteQuery({
    queryKey: ["chunks", id],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      api<{ items: Chunk[]; next_offset: number | null }>(
        `/api/backend/documents/${id}/chunks?offset=${pageParam}`,
      ),
    getNextPageParam: (last) => last.next_offset ?? undefined,
  });
  return (
    <div className="chunk-preview">
      <h3>解析内容与来源位置</h3>
      {query.isPending && <p role="status">正在加载解析内容…</p>}
      {query.error && (
        <p role="alert">
          {query.error.message}{" "}
          <button onClick={() => query.refetch()}>重试加载</button>
        </p>
      )}
      {query.data?.pages
        .flatMap((p) => p.items)
        .map((chunk) => (
          <div key={chunk.id} className="chunk">
            <p className="muted">
              片段 {chunk.ordinal + 1}
              {chunk.page_number ? ` · 第 ${chunk.page_number} 页` : ""}
              {chunk.section_path.length
                ? ` · ${chunk.section_path.join(" / ")}`
                : ""}
              {typeof chunk.metadata.line_start === "number"
                ? ` · 行 ${chunk.metadata.line_start}–${chunk.metadata.line_end}`
                : ""}
              {typeof chunk.metadata.body_block === "number"
                ? ` · 正文位置 ${chunk.metadata.body_block}`
                : ""}
            </p>
            <pre>{chunk.content}</pre>
          </div>
        ))}
      {query.data?.pages[0].items.length === 0 && (
        <p>尚无解析内容，请等待处理完成或重试任务。</p>
      )}
      {query.hasNextPage && (
        <button
          disabled={query.isFetchingNextPage}
          onClick={() => query.fetchNextPage()}
        >
          加载更多片段
        </button>
      )}
    </div>
  );
}
