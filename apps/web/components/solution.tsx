"use client";
import Link from "next/link";
import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { components } from "../../../packages/contracts/api";
import { api } from "../lib/client";
import { SolutionDeliveries } from "./solution-deliveries";
import { SolutionEditor } from "./solution-editor";
import { SolutionOutline } from "./solution-outline";

type Solution = components["schemas"]["SolutionView"];
type Version = components["schemas"]["VersionView"];
type Info = components["schemas"]["VersionInfo"];
type Entry = components["schemas"]["OutlineEntry"];
export function SolutionWorkspace({
  projectId,
  workflowRunId,
}: {
  projectId: string;
  workflowRunId?: string;
}) {
  const cache = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState("");
  const [historical, setHistorical] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [instruction, setInstruction] = useState("");
  const pending = useRef({ key: "", id: "" });
  const query = useQuery({
    queryKey: ["solution", projectId],
    queryFn: () =>
      api<Solution | null>(`/api/backend/projects/${projectId}/solutions`),
    refetchInterval: 3000,
  });
  const solution = query.data;
  const history = useQuery({
    queryKey: ["solution-versions", solution?.id, solution?.version],
    queryFn: async () => {
      const all: Info[] = [];
      let after = 0;
      for (let page = 0; page < 4; page++) {
        const batch = await api<Info[]>(
          `/api/backend/solutions/${solution!.id}/versions?after=${after}`,
        );
        all.push(...batch);
        if (batch.length < 50) break;
        after = batch.at(-1)!.version;
      }
      return all;
    },
    enabled: !!solution,
  });
  const old = useQuery({
    queryKey: ["solution-version", solution?.id, historical],
    queryFn: () =>
      api<Version>(
        `/api/backend/solutions/${solution!.id}/versions/${historical}`,
      ),
    enabled: !!solution && historical > 0,
  });
  const refresh = () => cache.invalidateQueries();
  const run = solution?.run;
  const running = run?.status === "queued" || run?.status === "running";
  const version = historical ? old.data : solution?.current;
  const section =
    version?.sections.find((s) => s.id === selected) ?? version?.sections[0];
  async function action(path: string, data?: object, method = "POST") {
    setBusy(true);
    setError("");
    const key = JSON.stringify({ path, data });
    if (pending.current.key !== key)
      pending.current = { key, id: crypto.randomUUID() };
    try {
      await api(
        path,
        method,
        data && { ...data, request_id: pending.current.id },
      );
      pending.current = { key: "", id: "" };
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }
  async function create() {
    setBusy(true);
    setError("");
    try {
      await api(`/api/backend/projects/${projectId}/solutions`, "POST", {
        workflow_run_id: workflowRunId,
        title: "项目解决方案",
      });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }
  const root = `/api/backend/solutions/${solution?.id}`;
  return (
    <div className="detail solution-workspace">
      <Link href={`/projects/${projectId}/overview`}>← 项目总览</Link>
      <div className="page-heading">
        <div>
          <p className="eyebrow">方案工作台</p>
          <h1>{solution?.title ?? "方案与版本"}</h1>
          <p className="muted">
            来源可追溯，版本可回看；AI 内容始终需要人工核实。
          </p>
        </div>
        <Link href={`/projects/${projectId}/dialogue`}>澄清与编排 →</Link>
      </div>
      {(error || query.error) && (
        <p className="error" role="alert">
          {error || query.error?.message}
        </p>
      )}
      {query.isPending && <p role="status">正在读取方案…</p>}
      {query.data === null && (
        <section className="panel">
          <h2>开始方案</h2>
          <p>先完成需求与编排，再从编排结果进入本页。</p>
          {workflowRunId ? (
            <button
              className="primary"
              disabled={busy}
              onClick={() => void create()}
            >
              采用编排结果创建方案
            </button>
          ) : (
            <Link href={`/projects/${projectId}/dialogue`}>前往编排 →</Link>
          )}
        </section>
      )}
      {solution && (
        <>
          {!solution.writable && <p className="notice">当前只读。</p>}
          <div className="panel solution-controls">
            <label>
              查看版本
              <select
                disabled={dirty || busy}
                value={historical}
                onChange={(e) => setHistorical(Number(e.target.value))}
              >
                <option value={0}>当前版本 {solution.version}</option>
                {history.data?.map((v) => (
                  <option key={v.id} value={v.version}>
                    版本 {v.version} · {v.change_summary}
                  </option>
                ))}
              </select>
            </label>
            {history.error && <p role="alert">版本列表读取失败。</p>}
            {run && (
              <p role="status">
                运行：
                {
                  (
                    {
                      queued: "排队中",
                      running: "处理中",
                      succeeded: "已完成",
                      failed: "失败，保存的版本保留",
                      cancelled: "已取消",
                    } as Record<string, string>
                  )[run.status]
                }{" "}
                {run.error_message}
              </p>
            )}
            {solution.writable && running && (
              <button
                disabled={busy}
                onClick={() =>
                  void action(`/api/backend/runs/${run!.id}/cancel`)
                }
              >
                取消运行
              </button>
            )}
            {solution.writable && !historical && (
              <label>
                生成补充要求
                <textarea
                  maxLength={2000}
                  value={instruction}
                  onChange={(e) => setInstruction(e.target.value)}
                />
                <span className="muted">
                  生成会把相关已确认需求与检索资料发送到已配置的 DeepSeek。
                </span>
              </label>
            )}
          </div>
          {historical > 0 && (
            <p className="notice">
              历史版本 {historical}，只读。当前版本为 {solution.version}。
            </p>
          )}
          {version && (
            <SolutionDeliveries
              solutionId={solution.id}
              version={version.version}
              writable={solution.writable}
              disabled={dirty || busy || !!running}
              selectSection={setSelected}
            />
          )}
          {old.error && historical > 0 && (
            <p role="alert" className="error">
              {old.error.message}
            </p>
          )}
          {solution.status === "outlining" && !historical && (
            <>
              {solution.writable && (
                <button
                  disabled={busy || running}
                  onClick={() =>
                    void action(root + "/outline", {
                      version: solution.version,
                      instruction,
                    })
                  }
                >
                  生成定制大纲
                </button>
              )}
              <SolutionOutline
                key={solution.version}
                sections={solution.current.sections}
                disabled={!solution.writable || busy || running}
                approve={(sections: Entry[]) =>
                  action(root + "/outline/approve", {
                    version: solution.version,
                    instruction,
                    sections,
                  })
                }
              />
            </>
          )}
          {version &&
            section &&
            (historical > 0 || solution.status !== "outlining") && (
              <div className="solution-grid">
                <nav className="panel solution-sections" aria-label="方案章节">
                  <h2>章节</h2>
                  {version.sections.map((s) => (
                    <button
                      key={s.id}
                      disabled={dirty || busy}
                      aria-current={s.id === section.id ? "true" : undefined}
                      onClick={() => setSelected(s.id)}
                    >
                      {s.title}
                      <small>
                        {s.status === "pending" ? "待生成" : "草稿"}
                      </small>
                    </button>
                  ))}
                </nav>
                <SolutionEditor
                  key={`${section.id}:${historical}`}
                  solutionId={solution.id}
                  section={section}
                  version={version.version}
                  writable={solution.writable && !historical}
                  onDirty={setDirty}
                  refresh={refresh}
                />
                <aside className="panel solution-sources">
                  <h2>本章来源</h2>
                  {solution.writable && !historical && (
                    <button
                      disabled={busy || running || dirty}
                      onClick={() =>
                        void action(root + `/sections/${section.id}/generate`, {
                          version: solution.version,
                          instruction,
                        })
                      }
                    >
                      {section.status === "pending"
                        ? "生成本章"
                        : "重新生成本章"}
                    </button>
                  )}
                  {!section.citations.length && (
                    <p className="notice">暂无引用，本章内容待进一步核实。</p>
                  )}
                  {section.citations.map((c) => (
                    <details key={c.id}>
                      <summary>
                        [{c.id}] {c.title}
                      </summary>
                      <p>{c.claim_text}</p>
                      <blockquote>{c.quote}</blockquote>
                      <p className="muted">
                        {c.verification_status === "unverified"
                          ? "人工修改后待重新核实"
                          : "摘录匹配，主张待核实"}
                      </p>
                      {c.document_id && (
                        <a
                          href={`/api/backend/documents/${c.document_id}/download`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          打开原文件（需当前权限）
                        </a>
                      )}
                      <p className="muted">
                        {c.locator?.page_number
                          ? `页 ${c.locator?.page_number}`
                          : ""}{" "}
                        {Array.isArray(c.locator?.section_path)
                          ? c.locator?.section_path.join(" / ")
                          : ""}
                      </p>
                    </details>
                  ))}
                </aside>
              </div>
            )}
        </>
      )}
    </div>
  );
}
