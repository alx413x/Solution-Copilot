"use client";
import Link from "next/link";
import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { components } from "../../../packages/contracts/api";
import { api } from "../lib/client";

type Run = components["schemas"]["RunView"];
export function Workflow({
  conversationId,
  projectId,
  epoch,
  writable,
}: {
  conversationId: string;
  projectId: string;
  epoch: number;
  writable: boolean;
}) {
  const cache = useQueryClient();
  const [goal, setGoal] = useState("生成项目解决方案");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef({ key: "", id: "" });
  const path = `/api/backend/conversations/${conversationId}/workflows`;
  const query = useQuery({
    queryKey: ["workflow", conversationId],
    queryFn: () => api<Run | null>(path + "/latest"),
    refetchInterval: 3000,
  });
  const run = query.data;
  const waiting = run?.status === "waiting_user";
  const active =
    waiting || run?.status === "queued" || run?.status === "running";
  const workflow = run?.workflow;
  async function act(cancel = false) {
    setBusy(true);
    setError("");
    const key = active
      ? `${run!.id}:${workflow?.gate}:${cancel}`
      : `${goal}:${epoch}`;
    if (pending.current.key !== key)
      pending.current = { key, id: crypto.randomUUID() };
    try {
      if (active)
        await api(
          `/api/backend/runs/${run!.id}/${cancel ? "cancel" : "resume"}`,
          "POST",
          cancel
            ? undefined
            : {
                request_id: pending.current.id,
                gate: workflow!.gate,
                approve: true,
              },
        );
      else
        await api(path, "POST", {
          goal,
          epoch,
          request_id: pending.current.id,
        });
      pending.current = { key: "", id: "" };
      await cache.invalidateQueries();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel">
      {run?.status === "succeeded" && (
        <Link href={`/projects/${projectId}/solution?workflow=${run.id}`}>
          进入方案生成与编辑 →
        </Link>
      )}
      <h2>方案编排</h2>
      <p className="muted">
        确认需求与初步大纲后，进入方案页细化大纲、生成正文并保存版本。
      </p>
      {(error || query.error) && (
        <p className="error" role="alert">
          {error || query.error?.message}
        </p>
      )}
      {query.isPending && <p role="status">正在读取编排状态…</p>}
      {run && (
        <p role="status">
          {
            (
              {
                queued: "等待执行",
                running: "处理中",
                waiting_user:
                  workflow?.gate === 1
                    ? "请补齐八类需求并确认档案"
                    : "请审核下方大纲",
                succeeded: "编排已完成，可进入方案生成与编辑",
                failed: "运行失败",
                cancelled: "运行已取消",
              } as Record<string, string>
            )[run.status]
          }{" "}
          {run.error_message}
        </p>
      )}
      {workflow?.warnings.map((warning, i) => (
        <p className="notice" key={i}>
          {warning}
        </p>
      ))}
      {!!workflow?.outline.length && (
        <ol>
          {workflow.outline.map((s) => (
            <li key={s.id}>{s.title}</li>
          ))}
        </ol>
      )}
      {waiting && workflow?.gate === 1 && (
        <Link href={`/projects/${projectId}/requirements`}>
          打开需求档案并确认 →
        </Link>
      )}
      {writable && !query.isPending && !query.error && (
        <div className="record-form">
          {!active && (
            <label>
              编排目标
              <input
                value={goal}
                maxLength={500}
                onChange={(e) => setGoal(e.target.value)}
              />
            </label>
          )}
          <div className="actions">
            {(!active || waiting) && (
              <button
                className="primary"
                disabled={busy || !goal.trim()}
                onClick={() => void act()}
              >
                {!active
                  ? "开始方案编排"
                  : workflow?.gate === 1
                    ? "需求已确认，继续"
                    : "确认此大纲"}
              </button>
            )}
            {active && (
              <button disabled={busy} onClick={() => void act(true)}>
                取消编排
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
