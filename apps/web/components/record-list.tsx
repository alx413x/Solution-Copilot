"use client";
import Link from "next/link";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, Customer, Project, Page } from "../lib/client";
import { RecordForm } from "./record-form";
import { useRole } from "./shell";
export function RecordList({
  kind,
  customerId,
  canCreate = true,
}: {
  kind: "customers" | "projects";
  customerId?: string;
  canCreate?: boolean;
}) {
  const role = useRole();
  const cache = useQueryClient();
  const [archived, setArchived] = useState(false);
  const [creating, setCreating] = useState(false);
  const query = useInfiniteQuery({
    queryKey: [kind, customerId, archived],
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      api<Page<Customer | Project>>(
        `/api/backend/${kind}?archived=${archived}${customerId ? "&customer_id=" + customerId : ""}${pageParam ? "&after=" + pageParam : ""}`,
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const Heading = customerId ? "h2" : "h1";
  const label = kind === "customers" ? "客户" : "项目";
  const allowed =
    canCreate &&
    (kind === "customers"
      ? role === "owner"
      : !!customerId && !!role && role !== "viewer");
  return (
    <div className="list-section">
      <div className="page-heading">
        <div>
          <p className="eyebrow">
            {kind === "customers" ? "客户关系" : "方案工作"}
          </p>
          <Heading>{customerId ? "客户项目" : label + "管理"}</Heading>
          <p className="muted">
            {kind === "customers"
              ? "建立客户背景，集中管理每一次方案合作。"
              : "从项目开始，逐步收集需求与形成方案。"}
          </p>
        </div>
        {allowed && !archived && (
          <button className="primary" onClick={() => setCreating(true)}>
            新建{label}
          </button>
        )}
      </div>
      {creating && (
        <div className="panel">
          <h2>新建{label}</h2>
          <RecordForm
            kind={kind === "customers" ? "customer" : "project"}
            onCancel={() => setCreating(false)}
            onSave={async (fields) => {
              await api(
                kind === "customers"
                  ? "/api/backend/customers"
                  : `/api/backend/customers/${customerId}/projects`,
                "POST",
                kind === "customers"
                  ? {
                      name: fields.name,
                      industry: fields.industry,
                      region: fields.region,
                      company_size: fields.company_size,
                    }
                  : { name: fields.name, description: fields.description },
              );
              await cache.invalidateQueries({ queryKey: [kind] });
              setCreating(false);
            }}
          />
        </div>
      )}
      <div className="tabs" aria-label="记录状态">
        <button aria-pressed={!archived} onClick={() => setArchived(false)}>
          进行中
        </button>
        <button
          aria-pressed={archived}
          onClick={() => {
            setArchived(true);
            setCreating(false);
          }}
        >
          已归档
        </button>
      </div>
      {query.isPending ? (
        <p role="status">正在加载{label}…</p>
      ) : query.error ? (
        <div role="alert" className="notice">
          {query.error.message}{" "}
          <button onClick={() => query.refetch()}>重试</button>
        </div>
      ) : (
        <>
          <div className="records">
            {query.data.pages
              .flatMap((page) => page.items)
              .map((item) => (
                <Link
                  className="record"
                  key={item.id}
                  href={
                    kind === "customers"
                      ? `/customers/${item.id}`
                      : `/projects/${item.id}/overview`
                  }
                >
                  <span>
                    <strong>{item.name}</strong>
                    <small>
                      {"industry" in item
                        ? [item.industry, item.region]
                            .filter(Boolean)
                            .join(" · ") || "尚未填写背景"
                        : item.description || "尚未填写项目简介"}
                    </small>
                  </span>
                  <span className="tag">
                    {"status" in item
                      ? item.status === "archived"
                        ? "已归档"
                        : "需求收集"
                      : item.deleted_at
                        ? "已归档"
                        : "客户档案"}
                  </span>
                </Link>
              ))}
          </div>
          {query.data.pages[0].items.length === 0 && (
            <div className="empty">
              <h2>
                暂无{archived ? "已归档" : ""}
                {label}
              </h2>
              <p>
                {kind === "projects" && !customerId
                  ? "请进入客户档案，新建该客户的项目。"
                  : allowed
                    ? "点击新建，开始记录。"
                    : "当前范围没有可查看的记录。"}
              </p>
            </div>
          )}
          {query.hasNextPage && (
            <button
              disabled={query.isFetchingNextPage}
              onClick={() => query.fetchNextPage()}
            >
              加载更多
            </button>
          )}
        </>
      )}
    </div>
  );
}
