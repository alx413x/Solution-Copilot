"use client";
import { useState } from "react";
import { useForm } from "react-hook-form";
import type { components } from "../../../packages/contracts/api";

export type Item = components["schemas"]["ItemView"];
type Fields = components["schemas"]["ItemInput"];
export const categories: Record<Fields["category"], string> = {
  background: "客户背景",
  pain_point: "业务痛点",
  goal: "建设目标",
  functional: "功能需求",
  non_functional: "非功能需求",
  integration: "系统集成",
  data: "数据需求",
  security_compliance: "安全与合规",
  constraint: "约束条件",
  timeline_budget: "时间与预算",
  acceptance_metric: "验收指标",
  risk: "风险",
};
const statuses = {
  proposed: "待确认",
  confirmed: "已确认",
  rejected: "已拒绝",
  conflicted: "待解决冲突",
};
export function ItemForm({
  item,
  save,
  cancel,
}: {
  item?: Item;
  save: (data: Fields) => Promise<void>;
  cancel?: () => void;
}) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { isSubmitting },
  } = useForm<Fields>({
    defaultValues: item
      ? {
          category: item.category,
          title: item.title,
          content: item.content,
          priority: item.priority,
        }
      : {
          category: "functional",
          title: "",
          content: "",
          priority: "unknown",
        },
  });
  const [error, setError] = useState("");
  return (
    <form
      className="record-form"
      onSubmit={handleSubmit(async (fields) => {
        setError("");
        try {
          await save(fields);
          if (!item) reset();
        } catch (e) {
          setError(e instanceof Error ? e.message : "保存失败");
        }
      })}
    >
      <label>
        分类
        <select {...register("category")}>
          {Object.entries(categories).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        标题
        <input
          {...register("title", { required: true })}
          required
          maxLength={240}
        />
      </label>
      <label>
        需求内容
        <textarea
          {...register("content", { required: true })}
          required
          maxLength={4000}
          rows={3}
        />
      </label>
      <label>
        优先级
        <select {...register("priority")}>
          <option value="unknown">未明确</option>
          <option value="must">必须</option>
          <option value="should">应该</option>
          <option value="could">可选</option>
        </select>
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        <button disabled={isSubmitting}>保存需求</button>
        {cancel && (
          <button type="button" onClick={cancel}>
            取消编辑
          </button>
        )}
      </div>
    </form>
  );
}
export function RequirementItem({
  item,
  writable,
  busy,
  change,
  version,
}: {
  item: Item;
  writable: boolean;
  busy: boolean;
  change: (data: unknown) => Promise<void>;
  version: number;
}) {
  const [editing, setEditing] = useState(false);
  const [editVersion, setEditVersion] = useState(version);
  return (
    <article className="panel">
      <h3>{item.title}</h3>
      <p>
        {statuses[item.status]} · {item.edited ? "人工编辑" : "模型提取"}
      </p>
      {editing ? (
        <ItemForm
          item={item}
          cancel={() => setEditing(false)}
          save={async (fields) => {
            await change({
              item_id: item.id,
              item: fields,
              version: editVersion,
            });
            setEditing(false);
          }}
        />
      ) : (
        <p className="description">{item.content}</p>
      )}
      {item.confidence !== null && (
        <p className="muted">
          提取置信度 {Math.round(item.confidence * 100)}%（不代表事实真实性）
        </p>
      )}
      {item.sources.map((s, index) => (
        <details key={index}>
          <summary>来源：{s.title}</summary>
          <p>
            {s.section_path?.join(" / ")}
            {s.page_number ? ` · 第 ${s.page_number} 页` : ""}
            {s.line_start
              ? ` · 行 ${s.line_start}–${s.line_end ?? s.line_start}`
              : ""}
          </p>
          <blockquote>{s.quote}</blockquote>
          {s.document_id && (
            <a href={`/api/backend/documents/${s.document_id}/download`}>
              下载来源原文
            </a>
          )}
        </details>
      ))}
      {writable && !editing && (
        <div className="actions">
          <button
            disabled={busy}
            onClick={() => {
              setEditVersion(version);
              setEditing(true);
            }}
          >
            编辑需求
          </button>
          {item.status === "conflicted" ? (
            <>
              <button
                disabled={busy}
                onClick={() =>
                  void change({ item_id: item.id, resolve_with: "keep" }).catch(
                    () => {},
                  )
                }
              >
                保留原项
              </button>
              <button
                disabled={busy}
                onClick={() =>
                  void change({
                    item_id: item.id,
                    resolve_with: "replace",
                  }).catch(() => {})
                }
              >
                采用此项并拒绝原项
              </button>
            </>
          ) : (
            <>
              <button
                disabled={busy || item.status === "confirmed"}
                onClick={() =>
                  void change({ item_id: item.id, status: "confirmed" }).catch(
                    () => {},
                  )
                }
              >
                确认此项
              </button>
              <button
                disabled={busy || item.status === "rejected"}
                onClick={() =>
                  void change({ item_id: item.id, status: "rejected" }).catch(
                    () => {},
                  )
                }
              >
                拒绝此项
              </button>
            </>
          )}
        </div>
      )}
    </article>
  );
}
