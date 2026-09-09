"use client";
import { useState } from "react";
import type { components } from "../../../packages/contracts/api";
import { api } from "../lib/client";
type Question = components["schemas"]["ClarificationView"];
type Memory = components["schemas"]["MemoryView"];
type Message = components["schemas"]["MessageView"];
export function ClarificationPanel({
  projectId,
  conversationId,
  epoch,
  questions,
  writable,
  refresh,
}: {
  projectId: string;
  conversationId: string;
  epoch: number;
  questions: Question[];
  writable: boolean;
  refresh: () => Promise<void>;
}) {
  const [draft, setDraft] = useState<{
    id: string;
    version: number;
    profile_version: number;
    epoch: number;
    answer: string;
  } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function act(fn: () => Promise<unknown>) {
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
  return (
    <section className="panel">
      <h2>澄清问题</h2>
      <p className="muted">
        必答问题用于补齐八类需求；建议问题可以跳过。回答保存为待确认需求。
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {writable && (
        <button
          disabled={busy}
          onClick={() =>
            act(() =>
              api(`/api/backend/projects/${projectId}/clarifications`, "POST"),
            )
          }
        >
          检查缺失信息
        </button>
      )}
      {!questions.length && (
        <p className="muted">尚未生成问题，请先新建会话并检查缺失信息。</p>
      )}
      {questions.map((q) => (
        <div key={q.id} className="requirement-item">
          <h3>{q.question}</h3>
          <p className="muted">
            {q.importance === "required" ? "必答" : "建议"} ·{" "}
            {
              (
                {
                  open: "待回答",
                  answered: "已回答",
                  skipped: "已跳过",
                } as Record<string, string>
              )[q.status]
            }{" "}
            · {q.reason}
          </p>
          {q.answer && <p className="description">{q.answer}</p>}
          {writable && draft?.id !== q.id && (
            <div className="actions">
              <button
                disabled={busy}
                onClick={() =>
                  act(async () => {
                    const profile = await api<{ version: number }>(
                      `/api/backend/projects/${projectId}/requirements`,
                    );
                    setDraft({
                      id: q.id,
                      version: q.version,
                      profile_version: profile.version,
                      epoch,
                      answer: q.answer ?? "",
                    });
                  })
                }
              >
                {q.status === "answered" ? "补充回答" : "回答"}
              </button>
              {q.importance === "recommended" && q.status === "open" && (
                <button
                  disabled={busy}
                  onClick={() =>
                    act(() =>
                      api(`/api/backend/clarifications/${q.id}/skip`, "POST", {
                        version: q.version,
                      }),
                    )
                  }
                >
                  跳过
                </button>
              )}
            </div>
          )}
          {draft?.id === q.id && (
            <form
              className="record-form"
              onSubmit={(e) => {
                e.preventDefault();
                void act(async () => {
                  await api(
                    `/api/backend/clarifications/${q.id}/answer`,
                    "POST",
                    {
                      conversation_id: conversationId,
                      answer: draft.answer,
                      version: draft.version,
                      profile_version: draft.profile_version,
                      epoch: draft.epoch,
                    },
                  );
                  setDraft(null);
                });
              }}
            >
              <label htmlFor={`answer-${q.id}`}>你的回答</label>
              <textarea
                id={`answer-${q.id}`}
                required
                maxLength={4000}
                value={draft.answer}
                onChange={(e) => setDraft({ ...draft, answer: e.target.value })}
              />
              <div className="actions">
                <button
                  className="primary"
                  disabled={busy || !writable || !draft.answer.trim()}
                >
                  保存回答
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setDraft(null)}
                >
                  取消
                </button>
              </div>
            </form>
          )}
        </div>
      ))}
    </section>
  );
}
export function MemoryPanel({
  projectId,
  sourceMessage,
  closeSource,
  memories,
  writable,
  refresh,
  onReset,
}: {
  projectId: string;
  sourceMessage: Message | null;
  closeSource: () => void;
  memories: Memory[];
  writable: boolean;
  refresh: () => Promise<void>;
  onReset: () => void;
}) {
  const source = sourceMessage?.id;
  const [content, setContent] = useState(
    sourceMessage?.content
      .filter((b) => b.type === "text")
      .map((b) => String(b.text))
      .join("\n")
      .slice(0, 2000) ?? "",
  );
  const [scope, setScope] = useState("project");
  const [draft, setDraft] = useState<Memory | null>(null);
  const [deleting, setDeleting] = useState<Memory | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function act(fn: () => Promise<unknown>) {
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
  return (
    <section className="panel">
      <h2>记忆</h2>
      <p className="muted">
        只有明确确认且未到期的记忆会进入后续模型上下文。客户记忆跨项目共享。
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {source && writable && (
        <form
          className="record-form"
          onSubmit={(e) => {
            e.preventDefault();
            void act(async () => {
              await api(`/api/backend/projects/${projectId}/memories`, "POST", {
                source_message_id: source,
                scope,
                content,
                kind: "fact",
              });
              closeSource();
            });
          }}
        >
          <label htmlFor="memory-content">记忆内容</label>
          <textarea
            id="memory-content"
            autoFocus
            required
            maxLength={2000}
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
          <label htmlFor="memory-scope">保存范围</label>
          <select
            id="memory-scope"
            value={scope}
            onChange={(e) => setScope(e.target.value)}
          >
            <option value="conversation">当前会话</option>
            <option value="project">当前项目</option>
            <option value="customer">当前客户（跨项目）</option>
          </select>
          <div className="actions">
            <button disabled={busy || !content.trim()}>保存待确认记忆</button>
            <button type="button" disabled={busy} onClick={() => closeSource()}>
              取消
            </button>
          </div>
        </form>
      )}
      {!memories.length && (
        <p className="muted">暂无有效记忆。可从对话消息保存一条。</p>
      )}
      {memories.map((m) => (
        <div key={m.id} className="requirement-item">
          <p className="eyebrow">
            {
              (
                {
                  customer: "客户",
                  project: "项目",
                  conversation: "会话",
                } as Record<string, string>
              )[m.scope]
            }{" "}
            · {m.status === "confirmed" ? "已确认" : "待确认"}
          </p>
          <p className="description">{m.content}</p>
          <MessageSource id={m.source_message_id} />
          {writable && (
            <div className="actions">
              <button disabled={busy} onClick={() => setDraft({ ...m })}>
                编辑 / 确认
              </button>
              <button disabled={busy} onClick={() => setDeleting(m)}>
                删除…
              </button>
            </div>
          )}
          {draft?.id === m.id && (
            <form
              className="record-form"
              onSubmit={(e) => {
                e.preventDefault();
                void act(async () => {
                  await api(`/api/backend/memories/${m.id}`, "PATCH", {
                    version: draft.version,
                    content: draft.content,
                    status: "confirmed",
                    expires_at: draft.expires_at,
                  });
                  setDraft(null);
                });
              }}
            >
              <label htmlFor={`memory-${m.id}`}>确认内容</label>
              <textarea
                id={`memory-${m.id}`}
                required
                maxLength={2000}
                value={draft.content}
                onChange={(e) =>
                  setDraft({ ...draft, content: e.target.value })
                }
              />
              <div className="actions">
                <button disabled={busy || !writable || !draft.content.trim()}>
                  确认记忆
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setDraft(null)}
                >
                  取消
                </button>
              </div>
            </form>
          )}
        </div>
      ))}
      {deleting && (
        <div className="notice" role="alert">
          <p>
            确认删除这条{deleting.scope === "customer" ? "客户" : ""}
            记忆？删除后不再用于后续对话。
          </p>
          <div className="actions">
            <button
              disabled={busy || !writable}
              onClick={() =>
                act(async () => {
                  await api(`/api/backend/memories/${deleting.id}`, "DELETE", {
                    version: deleting.version,
                  });
                  setDeleting(null);
                })
              }
            >
              确认删除
            </button>
            <button disabled={busy} onClick={() => setDeleting(null)}>
              取消
            </button>
          </div>
        </div>
      )}
      {writable && (
        <button disabled={busy} onClick={onReset}>
          重置项目记忆…
        </button>
      )}
    </section>
  );
}

function MessageSource({ id }: { id: string }) {
  const [source, setSource] = useState<Message | null>(null);
  const [error, setError] = useState("");
  return (
    <details
      onToggle={(e) => {
        if (e.currentTarget.open && !source)
          void api<Message>(`/api/backend/messages/${id}`)
            .then(setSource)
            .catch((e) => setError(e.message));
      }}
    >
      <summary>查看来源消息</summary>
      {error ? (
        <p role="alert">{error}</p>
      ) : source ? (
        source.content
          .filter((b) => b.type === "text")
          .map((b, i) => <blockquote key={i}>{String(b.text)}</blockquote>)
      ) : (
        <p role="status">正在读取来源…</p>
      )}
    </details>
  );
}
