"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import type { components } from "../../../packages/contracts/api";
import { api } from "../lib/client";

const rules: Record<string, string> = {
  requirement_coverage: "需求覆盖",
  required_clarification: "必答澄清",
  contradiction: "章节矛盾",
  factual_citation: "事实引用",
  citation_scope: "来源可用性",
  customer_leak: "客户信息",
  unsupported_promise: "能力承诺",
  acceptance_metric: "验收指标",
  incomplete_section: "章节完整性",
  unverified_content: "内容待核实",
};
type Delivery = components["schemas"]["DeliveryView"];
export function SolutionDeliveries({
  solutionId,
  version,
  writable,
  disabled,
  selectSection,
}: {
  solutionId: string;
  version: number;
  writable: boolean;
  disabled: boolean;
  selectSection: (id: string) => void;
}) {
  const cache = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef({ key: "", id: "" });
  const root = `/api/backend/solutions/${solutionId}`;
  const query = useQuery({
    queryKey: ["solution-deliveries", solutionId, version],
    queryFn: () => api<Delivery[]>(`${root}/deliveries?version=${version}`),
    refetchInterval: 3000,
  });
  async function start(format?: "markdown" | "docx") {
    setBusy(true);
    setError("");
    const key = `${solutionId}:${version}:${format ?? "verify"}`;
    if (pending.current.key !== key)
      pending.current = { key, id: crypto.randomUUID() };
    try {
      await api(root + (format ? "/exports" : "/verify"), "POST", {
        version,
        request_id: pending.current.id,
        ...(format ? { format } : {}),
      });
      pending.current = { key: "", id: "" };
      await cache.invalidateQueries();
    } catch (e) {
      setError(e instanceof Error ? e.message : "请求失败");
    } finally {
      setBusy(false);
    }
  }
  const running = query.data?.some((d) =>
    ["queued", "running"].includes(d.run.status),
  );
  const review = query.data?.find(
    (d) => d.kind === "verify" && d.run.status === "succeeded",
  );
  return (
    <section className="panel solution-deliveries" aria-label="质量检查与导出">
      <h2>质量检查与导出 · 版本 {version}</h2>
      <p className="muted">
        校验会将此版本的正文、引用和已确认需求发送到已配置的
        DeepSeek。问题与覆盖率是审核建议，仍需人工核实。
      </p>
      {writable && (
        <div className="actions">
          <button
            disabled={disabled || busy || running}
            onClick={() => void start()}
          >
            校验此版本
          </button>
          <button
            disabled={disabled || busy || running}
            onClick={() => void start("markdown")}
          >
            导出 Markdown
          </button>
          <button
            disabled={disabled || busy || running}
            onClick={() => void start("docx")}
          >
            导出 DOCX
          </button>
        </div>
      )}
      {disabled && <p className="muted">请先保存编辑并等待当前任务完成。</p>}
      {(error || query.error) && (
        <p role="alert" className="error">
          {error || query.error?.message}
        </p>
      )}
      {query.isPending && <p role="status">正在读取校验与导出记录…</p>}
      {query.data?.map((d) => (
        <div key={d.run.id} className="delivery-row">
          <p role="status">
            {d.kind === "verify"
              ? "质量检查"
              : d.format === "docx"
                ? "DOCX"
                : "Markdown"}{" "}
            ·{" "}
            {{
              queued: "排队中",
              running: "处理中",
              succeeded: "已完成",
              failed: "失败",
              cancelled: "已取消",
            }[d.run.status] ?? d.run.status}{" "}
            {d.run.error_message}
          </p>
          {d.download_url && (
            <a
              href={`/api/backend/exports/${d.run.id}/download`}
              target="_blank"
              rel="noreferrer"
            >
              下载 {d.format === "docx" ? "DOCX" : "Markdown"} · 版本{" "}
              {d.version}
            </a>
          )}
        </div>
      ))}
      {review && (
        <details open>
          <summary>
            最近一次成功校验 · {review.issues?.length ?? 0} 项提示 · 需求覆盖率{" "}
            {review.coverage_percent == null
              ? "无已确认需求"
              : `${review.coverage_percent}%`}
          </summary>
          <p className="muted">
            基于需求档案版本 {review.profile_version}
            ；方案或需求修改后请重新校验。导出保留待核实标记。
          </p>
          {review.issues?.map((issue, i) => (
            <div className="quality-issue" key={i}>
              <p>
                <strong>
                  {
                    { error: "需处理", warning: "需核实", info: "提示" }[
                      issue.severity
                    ]
                  }
                </strong>{" "}
                · {rules[issue.rule_id]}
              </p>
              <p>{issue.explanation}</p>
              <p>{issue.suggestion}</p>
              {issue.section_id && (
                <button
                  disabled={disabled}
                  onClick={() => selectSection(issue.section_id!)}
                >
                  定位章节
                </button>
              )}
            </div>
          ))}
        </details>
      )}
    </section>
  );
}
