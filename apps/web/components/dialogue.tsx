"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { components } from "../../../packages/contracts/api";
import { api } from "../lib/client";
import { Workflow } from "./workflow";
import { ClarificationPanel, MemoryPanel } from "./dialogue-records";

type Workspace = components["schemas"]["WorkspaceView"];
type History = components["schemas"]["HistoryView"];
type Run = components["schemas"]["RunView"];
export function Dialogue({
  projectId,
  initialConversation = "",
  initialAfter = 0,
}: {
  projectId: string;
  initialConversation?: string;
  initialAfter?: number;
}) {
  const base = `/api/backend/projects/${projectId}`;
  const cache = useQueryClient();
  const [selected, select] = useState(initialConversation);
  const [after, setAfter] = useState(initialAfter);
  const [memoryMessage, setMemoryMessage] = useState<
    History["messages"][number] | null
  >(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [streamStatus, setStreamStatus] = useState("");
  const [preview, setPreview] = useState<{
    path: string;
    memories: number;
    context_messages: number;
    runs: number;
  } | null>(null);
  const pending = useRef<{
    text: string;
    request_id: string;
    epoch: number;
  } | null>(null);
  const workspace = useQuery({
    queryKey: ["dialogue", projectId],
    queryFn: () => api<Workspace>(base + "/dialogue"),
  });
  const id = selected || workspace.data?.conversations.at(-1)?.id || "";
  const history = useQuery({
    queryKey: ["messages", id, after],
    queryFn: () =>
      api<History>(`/api/backend/conversations/${id}/messages?after=${after}`),
    enabled: !!id,
    refetchInterval: 5000,
  });
  const run = history.data?.run;
  const running = run?.status === "queued" || run?.status === "running";
  const refresh = async () => {
    await cache.invalidateQueries();
  };
  async function action(fn: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (!run || !running) return;
    const stream = new EventSource(`/api/backend/runs/${run.id}/events`);
    setStreamStatus("正在连接运行事件…");
    stream.onopen = () => setStreamStatus("运行已连接");
    stream.onerror = () =>
      setStreamStatus("连接中断，正在恢复；消息以保存结果为准。");
    for (const kind of [
      "run.started",
      "node.started",
      "message.delta",
      "citation.created",
      "run.waiting_user",
      "run.completed",
      "run.failed",
      "run.cancelled",
    ]) {
      stream.addEventListener(kind, () => {
        void cache.invalidateQueries({ queryKey: ["messages", id] });
      });
    }
    stream.addEventListener("stream.end", () => {
      stream.close();
      setStreamStatus("运行结果已保存");
      void cache.invalidateQueries();
    });
    stream.addEventListener("stream.denied", () => {
      stream.close();
      setStreamStatus("授权已失效，请重新登录或联系管理员。");
      void cache.invalidateQueries();
    });
    return () => stream.close();
  }, [run?.id, running, cache, id]);
  if (workspace.isPending) return <p role="status">正在加载澄清工作台…</p>;
  if (workspace.error)
    return (
      <p role="alert">
        {workspace.error.message}
        <button onClick={() => workspace.refetch()}>重试</button>
      </p>
    );
  const writable = workspace.data.writable;
  const epoch = history.data?.conversation.epoch ?? 0;
  return (
    <div className="detail">
      <Link href={`/projects/${projectId}/overview`}>← 项目总览</Link>
      <div className="page-heading">
        <div>
          <p className="eyebrow">需求收集</p>
          <h1>澄清与对话</h1>
          <p className="muted">
            回答补齐需求，来源保留；候选需求仍需人工确认。
          </p>
        </div>
        <Link href={`/projects/${projectId}/requirements`}>查看需求档案 →</Link>
      </div>
      {!writable && <p className="notice">当前为只读状态。</p>}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <section className="panel">
        <h2>项目会话</h2>
        <div className="actions">
          <label className="record-form">
            当前会话
            <select
              value={id}
              onChange={(e) => {
                select(e.target.value);
                setAfter(0);
                setText("");
                pending.current = null;
              }}
            >
              <option value="" disabled>
                请选择会话
              </option>
              {workspace.data.conversations.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title} · {c.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          {writable && (
            <button
              disabled={busy}
              onClick={() =>
                action(async () => {
                  const c = await api<{ id: string }>(
                    base + "/conversations",
                    "POST",
                    { title: "需求澄清" },
                  );
                  select(c.id);
                  setAfter(0);
                })
              }
            >
              新建会话
            </button>
          )}
        </div>
        {!id && (
          <p className="muted">新建会话后，可以发送消息或回答澄清问题。</p>
        )}
        {history.isFetching && !history.data && (
          <p role="status">正在加载消息…</p>
        )}
        {history.error && (
          <p role="alert" className="error">
            {history.error.message}
          </p>
        )}
        {history.data && (
          <>
            <p className="muted">
              当前上下文：第 {epoch + 1} 轮。重置前的消息仅供查阅。
            </p>
            {history.data.messages.length === 0 && (
              <p className="muted">还没有消息，请描述项目目标或补充需求。</p>
            )}
            <ol className="message-list">
              {history.data.messages.map((m) => (
                <li className="panel" key={m.id} id={`message-${m.id}`}>
                  <p className="eyebrow">
                    {m.role === "user" ? "用户" : "助手"} · 第 {m.epoch + 1} 轮
                    · {new Date(m.created_at).toLocaleString("zh-CN")}
                  </p>
                  {m.content.map((b, i) =>
                    b.type === "text" ? (
                      <p className="description" key={i}>
                        {String(b.text)}
                      </p>
                    ) : b.type === "citation" ? (
                      <details key={i}>
                        <summary>需求来源</summary>
                        <blockquote>{String(b.quote)}</blockquote>
                        <p>消息 {String(b.message_id)}</p>
                      </details>
                    ) : b.type === "tool_status" ? (
                      <p className="muted" key={i}>
                        回答：{String(b.question)}
                      </p>
                    ) : (
                      <p role="alert" key={i}>
                        {String(b.message ?? "运行错误")}
                      </p>
                    ),
                  )}
                  {writable && (
                    <button disabled={busy} onClick={() => setMemoryMessage(m)}>
                      保存为记忆…
                    </button>
                  )}
                </li>
              ))}
            </ol>
            <div className="actions">
              {after > 0 && (
                <button onClick={() => setAfter(0)}>返回最早消息</button>
              )}
              {history.data.next_after != null && (
                <button onClick={() => setAfter(history.data!.next_after!)}>
                  加载后续消息
                </button>
              )}
            </div>
            {run && (
              <p role="status">
                运行：
                {
                  (
                    {
                      queued: "排队中",
                      running: "处理中",
                      waiting_user: "等待补充信息",
                      succeeded: "已完成",
                      failed: "失败",
                      cancelled: "已取消",
                    } as Record<string, string>
                  )[run.status]
                }{" "}
                {run.error_message}
              </p>
            )}
            {streamStatus && (
              <p className="muted" role="status">
                {streamStatus}
              </p>
            )}
            {writable && (
              <form
                className="record-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  void action(async () => {
                    if (
                      !pending.current ||
                      pending.current.text !== text ||
                      pending.current.epoch !== epoch
                    )
                      pending.current = {
                        text,
                        request_id: crypto.randomUUID(),
                        epoch,
                      };
                    await api<Run>(
                      `/api/backend/conversations/${id}/messages`,
                      "POST",
                      pending.current,
                    );
                    pending.current = null;
                    setText("");
                  });
                }}
              >
                <label htmlFor="chat-input">补充需求或提问</label>
                <textarea
                  id="chat-input"
                  required
                  maxLength={4000}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
                <div className="actions">
                  <button
                    className="primary"
                    disabled={busy || running || !text.trim()}
                  >
                    发送
                  </button>
                  {running && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        action(() =>
                          api(`/api/backend/runs/${run!.id}/cancel`, "POST"),
                        )
                      }
                    >
                      取消运行
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      action(async () => {
                        const path = `/api/backend/conversations/${id}/reset`;
                        const result = await api<
                          Omit<NonNullable<typeof preview>, "path">
                        >(path, "POST", { confirm: false });
                        setPreview({ ...result, path });
                      })
                    }
                  >
                    重置会话…
                  </button>
                </div>
              </form>
            )}
          </>
        )}
      </section>
      {preview && (
        <section className="notice" role="alert">
          <h2>确认重置范围</h2>
          <p>
            将停用 {preview.memories} 条记忆、移出上下文{" "}
            {preview.context_messages} 条消息，取消 {preview.runs}{" "}
            个运行。历史消息和客户记忆保留。
          </p>
          <div className="actions">
            <button
              disabled={busy}
              onClick={() =>
                action(async () => {
                  await api(preview.path, "POST", { confirm: true });
                  setPreview(null);
                  pending.current = null;
                })
              }
            >
              确认重置
            </button>
            <button disabled={busy} onClick={() => setPreview(null)}>
              取消
            </button>
          </div>
        </section>
      )}
      {id && history.data && (
        <Workflow
          key={`workflow:${id}`}
          conversationId={id}
          projectId={projectId}
          epoch={epoch}
          writable={writable}
        />
      )}
      <ClarificationPanel
        key={id}
        projectId={projectId}
        conversationId={id}
        epoch={epoch}
        questions={workspace.data.clarifications}
        writable={writable && !!history.data}
        refresh={refresh}
      />
      <MemoryPanel
        projectId={projectId}
        key={memoryMessage?.id ?? "none"}
        sourceMessage={memoryMessage}
        closeSource={() => setMemoryMessage(null)}
        memories={workspace.data.memories}
        writable={writable}
        refresh={refresh}
        onReset={() =>
          action(async () => {
            const path = base + "/memories/reset";
            const result = await api<Omit<NonNullable<typeof preview>, "path">>(
              path,
              "POST",
              { confirm: false },
            );
            setPreview({ ...result, path });
          })
        }
      />
    </div>
  );
}
