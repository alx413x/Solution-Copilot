"use client";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, Customer, Project } from "../lib/client";
import { RecordForm } from "./record-form";
import { RecordList } from "./record-list";
import { useRole } from "./shell";
export function RecordDetail({
  kind,
  id,
}: {
  kind: "customers" | "projects";
  id: string;
}) {
  const role = useRole();
  const cache = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const query = useQuery({
    queryKey: [kind, id],
    queryFn: () => api<Customer | Project>(`/api/backend/${kind}/${id}`),
  });
  const parent = useQuery({
    queryKey: [
      "customers",
      "status",
      query.data && "customer_id" in query.data ? query.data.customer_id : "",
    ],
    queryFn: () =>
      api<Customer>(
        `/api/backend/customers/${(query.data as Project).customer_id}`,
      ),
    enabled: kind === "projects" && !!query.data,
  });
  if (query.isPending) return <p role="status">正在加载档案…</p>;
  if (query.error)
    return (
      <div role="alert" className="notice">
        {query.error.message}
        <button onClick={() => query.refetch()}>重试</button>
        <Link href={`/${kind}`}>返回列表</Link>
      </div>
    );
  const record = query.data;
  const archived =
    ("deleted_at" in record
      ? !!record.deleted_at
      : record.status === "archived") || !!parent.data?.deleted_at;
  const writable =
    !!role &&
    role !== "viewer" &&
    !archived &&
    (kind === "customers" || !!parent.data);
  return (
    <div className="detail">
      <Link className="back" href={`/${kind}`}>
        ← 返回{kind === "customers" ? "客户" : "项目"}列表
      </Link>
      <div className="page-heading">
        <div>
          <p className="eyebrow">
            {kind === "customers" ? "客户档案" : "项目总览"} ·{" "}
            {archived ? "已归档" : "进行中"}
          </p>
          <h1>{record.name}</h1>
          <p className="muted">
            更新于 {new Date(record.updated_at).toLocaleString("zh-CN")}
          </p>
        </div>
        {writable && !editing && (
          <div className="actions">
            <button onClick={() => setEditing(true)}>编辑</button>
            <button onClick={() => setConfirm(true)}>归档</button>
          </div>
        )}
      </div>
      {parent.error && (
        <p className="error" role="alert">
          客户状态无法读取，请刷新后重试。
        </p>
      )}
      {archived && (
        <p className="notice">该档案或所属客户已归档，内容保留供查阅。</p>
      )}
      {confirm && (
        <div className="notice" role="alert">
          <p>
            确认归档“{record.name}”？归档后仅供查阅
            {kind === "customers" ? "，该客户下的项目也将停止编辑" : ""}。
          </p>
          <div className="actions">
            <button
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  await api(
                    `/api/backend/${kind}/${id}${kind === "projects" ? "/archive" : ""}`,
                    kind === "projects" ? "POST" : "DELETE",
                    { version: record.version },
                  );
                  await cache.invalidateQueries();
                  setConfirm(false);
                } catch (e) {
                  setError(e instanceof Error ? e.message : "归档失败");
                } finally {
                  setBusy(false);
                }
              }}
            >
              确认归档
            </button>
            <button disabled={busy} onClick={() => setConfirm(false)}>
              取消
            </button>
          </div>
        </div>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {editing ? (
        <div className="panel">
          <RecordForm
            key={record.version}
            kind={kind === "customers" ? "customer" : "project"}
            initial={record}
            onCancel={() => setEditing(false)}
            onSave={async (fields) => {
              await api(
                `/api/backend/${kind}/${id}`,
                "PATCH",
                kind === "customers"
                  ? {
                      name: fields.name,
                      industry: fields.industry,
                      region: fields.region,
                      company_size: fields.company_size,
                      profile: (record as Customer).profile,
                      version: record.version,
                    }
                  : {
                      name: fields.name,
                      description: fields.description,
                      version: record.version,
                    },
              );
              await cache.invalidateQueries();
              setEditing(false);
            }}
          />
        </div>
      ) : (
        <div className="panel">
          {"industry" in record ? (
            <dl>
              <dt>行业</dt>
              <dd>{record.industry || "未填写"}</dd>
              <dt>地区</dt>
              <dd>{record.region || "未填写"}</dd>
              <dt>企业规模</dt>
              <dd>{record.company_size || "未填写"}</dd>
            </dl>
          ) : (
            <>
              <p>负责人：{record.owner_display_name}</p>
              <h2>项目简介</h2>
              <p className="description">
                {record.description || "尚未填写。"}
              </p>
              <p>
                <Link href={`/customers/${record.customer_id}`}>
                  查看所属客户
                </Link>
              </p>
              <p className="muted">
                当前阶段：{record.status === "archived" ? "已归档" : "需求收集"}
                。
              </p>
              <Link href={`/projects/${id}/knowledge`}>管理项目资料 →</Link>
            </>
          )}
        </div>
      )}
      {kind === "customers" && (
        <>
          <Link href={`/customers/${id}/knowledge`}>管理客户资料 →</Link>
          <RecordList kind="projects" customerId={id} canCreate={!archived} />
        </>
      )}
    </div>
  );
}
