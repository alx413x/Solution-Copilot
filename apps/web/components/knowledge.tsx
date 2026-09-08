"use client";
import Link from "next/link";
import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useState } from "react";
import {
  api,
  Customer,
  KnowledgeDocument,
  Page,
  Project,
  UploadResult,
} from "../lib/client";
import { useRole } from "./shell";
import { DocumentPreview } from "./document-preview";

const statuses: Record<string, string> = {
  uploaded: "等待处理",
  parsing: "正在解析",
  parsed: "解析完成",
  failed: "处理失败",
  disabled: "已停用",
  ready: "可检索",
  indexing: "正在索引",
};
export function Knowledge({
  scope,
  id,
}: {
  scope: "organization" | "customer" | "project";
  id?: string;
}) {
  const role = useRole();
  const cache = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const parent = useQuery<Customer | Project>({
    queryKey: [scope, id],
    enabled: !!id,
    queryFn: () =>
      scope === "project"
        ? api<Project>(`/api/backend/projects/${id}`)
        : api<Customer>(`/api/backend/customers/${id}`),
  });
  const customerId =
    scope === "customer"
      ? id
      : parent.data && "customer_id" in parent.data
        ? parent.data.customer_id
        : undefined;
  const customer = useQuery({
    queryKey: ["knowledge-customer", customerId],
    enabled: scope === "project" && !!customerId,
    queryFn: () => api<Customer>(`/api/backend/customers/${customerId}`),
  });
  const archived =
    !!(
      parent.data &&
      ("deleted_at" in parent.data
        ? parent.data.deleted_at
        : parent.data.status === "archived")
    ) || !!customer.data?.deleted_at;
  const writable =
    !!role &&
    role !== "viewer" &&
    !archived &&
    (scope === "organization" ? role === "owner" : !!parent.data) &&
    (scope !== "project" || !!customer.data);
  const filter = `scope=${scope}${id ? `&${scope}_id=${id}` : ""}`;
  const query = useInfiniteQuery({
    queryKey: ["documents", scope, id],
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      api<Page<KnowledgeDocument>>(
        `/api/backend/documents?${filter}${pageParam ? `&cursor=${pageParam}` : ""}`,
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    refetchInterval: 3000,
  });
  async function action(path: string, method = "POST") {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await api(`/api/backend/${path}`, method);
      setConfirm(null);
      setPreview(null);
      await cache.invalidateQueries({ queryKey: ["documents"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="list-section">
      {id && (
        <Link
          className="back"
          href={
            scope === "project"
              ? `/projects/${id}/overview`
              : `/customers/${id}`
          }
        >
          ← 返回档案
        </Link>
      )}
      <div className="page-heading">
        <div>
          <p className="eyebrow">知识与材料</p>
          <h1>
            {scope === "organization"
              ? "组织资料"
              : `${parent.data?.name ?? ""} · ${scope === "project" ? "项目" : "客户"}资料`}
          </h1>
          <p className="muted">上传原始材料，查看解析内容与来源位置。</p>
        </div>
      </div>
      {(parent.error || customer.error) && (
        <p role="alert" className="error">
          {parent.error?.message ?? customer.error?.message}
        </p>
      )}
      {archived && <p className="notice">所属档案已归档，资料仅供查阅。</p>}
      {writable && (
        <form
          className="panel record-form"
          onSubmit={async (event) => {
            event.preventDefault();
            const form = event.currentTarget;
            const data = new FormData(form);
            data.set("scope", scope);
            if (customerId) data.set("customer_id", customerId);
            if (scope === "project" && id) data.set("project_id", id);
            setBusy(true);
            setError("");
            setMessage("");
            try {
              const result = await api<UploadResult>(
                "/api/backend/documents",
                "POST",
                data,
              );
              setMessage(
                result.duplicate
                  ? "该作用域已有相同文件，已保留现有资料。"
                  : "上传已接收，处理进度将自动更新。",
              );
              form.reset();
              await cache.invalidateQueries({ queryKey: ["documents"] });
            } catch (e) {
              setError(e instanceof Error ? e.message : "上传失败");
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            选择资料
            <input
              type="file"
              name="file"
              accept=".txt,.md,.pdf,.docx"
              required
              disabled={busy}
              aria-describedby="upload-help"
            />
          </label>
          <small id="upload-help">
            支持 UTF-8 TXT、Markdown、PDF、DOCX，默认上限 25 MB。扫描 PDF
            请先进行 OCR。
          </small>
          <div>
            <button className="primary" disabled={busy}>
              {busy ? "正在提交…" : "上传并解析"}
            </button>
          </div>
        </form>
      )}
      {message && (
        <p role="status" className="notice">
          {message}
        </p>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {query.isPending && <p role="status">正在加载资料…</p>}
      {query.error && (
        <p role="alert">
          {query.error.message}{" "}
          <button onClick={() => query.refetch()}>重试加载</button>
        </p>
      )}
      {query.data?.pages[0].items.length === 0 && (
        <div className="empty">
          暂无资料。
          {writable
            ? "上传一份会议纪要或产品资料开始。"
            : "有权限的成员上传后，资料将在这里显示。"}
        </div>
      )}
      {query.data?.pages
        .flatMap((p) => p.items)
        .map((doc) => (
          <article className="panel document" key={doc.id}>
            <div className="heading">
              <h2>{doc.title}</h2>
              <span className="tag">{statuses[doc.status] ?? doc.status}</span>
            </div>
            {doc.job && (
              <p className="muted">
                处理进度 {doc.job.progress}% · 已尝试 {doc.job.attempts} 次
                {doc.job.status === "cancelled" ? " · 已取消" : ""}
              </p>
            )}
            {doc.error_message && <p className="error">{doc.error_message}</p>}
            {doc.status !== "disabled" && (
              <div className="actions">
                <a href={`/api/backend/documents/${doc.id}/download`}>
                  下载原文件
                </a>
                {doc.generation > 0 && (
                  <button
                    aria-expanded={preview === doc.id}
                    onClick={() =>
                      setPreview(preview === doc.id ? null : doc.id)
                    }
                  >
                    查看解析内容
                  </button>
                )}
                {writable &&
                  doc.job &&
                  ["failed", "cancelled"].includes(doc.job.status) && (
                    <button
                      disabled={busy}
                      onClick={() => action(`jobs/${doc.job!.id}/retry`)}
                    >
                      重试处理
                    </button>
                  )}
                {writable &&
                  doc.job &&
                  ["queued", "running"].includes(doc.job.status) && (
                    <button
                      disabled={busy}
                      onClick={() => action(`jobs/${doc.job!.id}/cancel`)}
                    >
                      取消处理
                    </button>
                  )}
                {writable && doc.status === "parsed" && (
                  <button
                    disabled={busy}
                    onClick={() => action(`documents/${doc.id}/reindex`)}
                  >
                    重新解析
                  </button>
                )}
                {writable && (
                  <button
                    disabled={busy}
                    onClick={() => action(`documents/${doc.id}/disable`)}
                  >
                    停用
                  </button>
                )}
              </div>
            )}
            {writable && (
              <button disabled={busy} onClick={() => setConfirm(doc.id)}>
                删除资料
              </button>
            )}
            {confirm === doc.id && (
              <div className="notice">
                <p>确认删除“{doc.title}”？原文件和解析内容将被清理。</p>
                <div className="actions">
                  <button
                    disabled={busy}
                    onClick={() => action(`documents/${doc.id}`, "DELETE")}
                  >
                    确认删除
                  </button>
                  <button disabled={busy} onClick={() => setConfirm(null)}>
                    保留资料
                  </button>
                </div>
              </div>
            )}
            {preview === doc.id && (
              <DocumentPreview
                key={`${doc.id}-${doc.generation}`}
                id={doc.id}
              />
            )}
          </article>
        ))}
      {query.hasNextPage && (
        <button
          disabled={query.isFetchingNextPage}
          onClick={() => query.fetchNextPage()}
        >
          加载更多资料
        </button>
      )}
    </div>
  );
}
