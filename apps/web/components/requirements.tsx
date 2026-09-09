"use client";
import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, KnowledgeDocument, Page, Project } from "../lib/client";
import type { components } from "../../../packages/contracts/api";
import { categories, ItemForm, RequirementItem } from "./requirement-item";
type Profile = components["schemas"]["ProfileView"];

export function Requirements({ projectId }: { projectId: string }) {
  const path = `/api/backend/projects/${projectId}/requirements`;
  const [text, setText] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [summaryDraft, setSummaryDraft] = useState<{
    text: string;
    version: number;
  } | null>(null);
  const query = useQuery({
    queryKey: ["requirements", projectId],
    queryFn: () => api<Profile>(path),
    refetchInterval: (q) =>
      ["queued", "running"].includes(q.state.data?.extraction?.status ?? "")
        ? 2000
        : false,
  });
  const project = useQuery({
    queryKey: ["projects", projectId],
    queryFn: () => api<Project>(`/api/backend/projects/${projectId}`),
  });
  const documents = useQuery({
    queryKey: ["requirement-sources", projectId],
    enabled: !!project.data,
    queryFn: async () => {
      const scopes = [
        `scope=organization`,
        `scope=customer&customer_id=${project.data!.customer_id}`,
        `scope=project&customer_id=${project.data!.customer_id}&project_id=${projectId}`,
      ];
      const pages = await Promise.all(
        scopes.map(async (scope) => {
          const all: KnowledgeDocument[] = [];
          let cursor: string | null = null;
          do {
            const page: Page<KnowledgeDocument> = await api(
              `/api/backend/documents?${scope}&limit=100${cursor ? `&after=${cursor}` : ""}`,
            );
            all.push(...page.items);
            cursor = page.next_cursor;
          } while (cursor);
          return all;
        }),
      );
      return pages.flat().filter((d) => ["parsed", "ready"].includes(d.status));
    },
  });
  async function change(data: unknown, suffix = "", method = "PATCH") {
    setBusy(true);
    setError("");
    try {
      await api(
        path + suffix,
        method,
        method === "PATCH"
          ? { version: query.data?.version, ...(data as object) }
          : data,
      );
      await query.refetch();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
      throw e;
    } finally {
      setBusy(false);
    }
  }
  if (query.isPending) return <p role="status">正在加载需求档案…</p>;
  if (query.error)
    return (
      <p role="alert">
        {query.error.message}
        <button onClick={() => query.refetch()}>重试</button>
      </p>
    );
  const profile = query.data;
  const running = ["queued", "running"].includes(
    profile.extraction?.status ?? "",
  );
  return (
    <div className="detail">
      <Link href={`/projects/${projectId}/overview`}>← 返回项目总览</Link>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{project.data?.name ?? "项目"}</p>
          <h1>需求档案</h1>
          <p>从材料提取需求，逐项核对来源并确认。</p>
        </div>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!profile.writable && <p className="notice">当前档案仅供查看。</p>}
      <section className="panel">
        <h2>完整度与摘要</h2>
        <p>
          类别完整度 {profile.completeness_score}% ·{" "}
          {profile.confirmed_at ? "档案已确认" : "档案待确认"}
        </p>
        <p>
          缺失类别：
          {profile.missing_categories
            .map((c) => categories[c as keyof typeof categories])
            .join("、") || "无"}
          。请核实，不适用项可明确记录原因。
        </p>
        <p className="description">{profile.summary || "尚无摘要。"}</p>
        {profile.writable && !summaryDraft && (
          <button
            onClick={() =>
              setSummaryDraft({
                text: profile.summary,
                version: profile.version,
              })
            }
          >
            编辑摘要
          </button>
        )}
        {profile.writable && summaryDraft && (
          <form
            className="record-form"
            onSubmit={(e) => {
              e.preventDefault();
              void change({
                summary: summaryDraft.text,
                version: summaryDraft.version,
              })
                .then(() => setSummaryDraft(null))
                .catch(() => {});
            }}
          >
            <label>
              编辑摘要
              <textarea
                name="summary"
                value={summaryDraft.text}
                onChange={(e) =>
                  setSummaryDraft({ ...summaryDraft, text: e.target.value })
                }
                maxLength={4000}
              />
            </label>
            <button disabled={busy}>保存摘要</button>
            <button type="button" onClick={() => setSummaryDraft(null)}>
              取消编辑摘要
            </button>
          </form>
        )}
      </section>
      {profile.writable && (
        <section className="panel">
          <h2>提取需求</h2>
          <p>
            所选材料和当前需求将发送到已配置的 DeepSeek
            服务。提取结果需人工核对。
          </p>
          <form
            className="record-form"
            onSubmit={(e) => {
              e.preventDefault();
              void change(
                { text, document_ids: selected },
                "/extractions",
                "POST",
              ).catch(() => {});
            }}
          >
            <label>
              会议纪要或原始需求
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                maxLength={30000}
                rows={5}
              />
            </label>
            <fieldset>
              <legend>选择已解析资料（最多 10 份）</legend>
              {documents.isPending && <p role="status">正在加载来源…</p>}
              {documents.error && <p role="alert">{documents.error.message}</p>}
              {documents.data?.map((d) => (
                <label key={d.id}>
                  <input
                    type="checkbox"
                    checked={selected.includes(d.id)}
                    disabled={!selected.includes(d.id) && selected.length >= 10}
                    onChange={(e) =>
                      setSelected(
                        e.target.checked
                          ? [...selected, d.id]
                          : selected.filter((id) => id !== d.id),
                      )
                    }
                  />
                  {d.title}
                </label>
              ))}
              {documents.data?.length === 0 && (
                <p>
                  暂无已解析资料，可先输入文本或
                  <Link href={`/projects/${projectId}/knowledge`}>
                    上传项目资料
                  </Link>
                  。
                </p>
              )}
            </fieldset>
            <button
              disabled={busy || running || (!text.trim() && !selected.length)}
            >
              提取需求
            </button>
          </form>
          {profile.extraction && (
            <div role="status">
              <p>
                最近任务：
                {{
                  queued: "等待处理",
                  running: "正在提取",
                  succeeded: "提取完成",
                  failed: "提取失败",
                  cancelled: "已取消",
                }[profile.extraction.status] ?? profile.extraction.status}{" "}
                · 已尝试 {profile.extraction.attempts} 次
              </p>
              {profile.extraction.error_message && (
                <p className="error">{profile.extraction.error_message}</p>
              )}
              {running && (
                <button
                  disabled={busy}
                  onClick={() =>
                    void change(
                      {},
                      `/extractions/${profile.extraction!.id}/cancel`,
                      "POST",
                    ).catch(() => {})
                  }
                >
                  取消提取
                </button>
              )}
            </div>
          )}
        </section>
      )}
      {profile.writable && (
        <div className="actions">
          <button disabled={busy} onClick={() => setAdding(!adding)}>
            {adding ? "收起新增" : "手动新增需求"}
          </button>
          <button
            disabled={
              busy ||
              !profile.items.length ||
              profile.items.some((i) => i.status === "conflicted")
            }
            onClick={() =>
              void change(
                { version: profile.version },
                "/confirm",
                "POST",
              ).catch(() => {})
            }
          >
            确认整个档案
          </button>
        </div>
      )}
      {adding && profile.writable && (
        <section className="panel">
          <h2>新增需求</h2>
          <ItemForm
            save={async (item) => {
              await change({ item });
              setAdding(false);
            }}
          />
        </section>
      )}
      {!profile.items.length && (
        <p role="status">尚无需求，请从材料提取或手动新增。</p>
      )}
      {Object.entries(categories)
        .filter(([key]) => profile.items.some((i) => i.category === key))
        .map(([key, label]) => (
          <section key={key}>
            <h2>{label}</h2>
            {profile.items
              .filter((i) => i.category === key)
              .map((item) => (
                <div key={item.id}>
                  {item.status === "conflicted" && (
                    <p className="notice">
                      与原项冲突：
                      {profile.items
                        .filter((i) => item.conflicts_with.includes(i.id))
                        .map((i) => i.content)
                        .join("；")}
                    </p>
                  )}
                  <RequirementItem
                    item={item}
                    writable={profile.writable}
                    busy={busy}
                    change={change}
                    version={profile.version}
                  />
                </div>
              ))}
          </section>
        ))}
    </div>
  );
}
