"use client";
import { useCallback, useEffect, useState } from "react";
import type { components } from "../../../packages/contracts/api";

type Report = components["schemas"]["HealthReport"];
const labels: Record<string, string> = { postgres: "数据库", redis: "任务队列", storage: "文件存储", api: "API 服务" };
export default function Home() {
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const check = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch("/api/health", { signal: AbortSignal.timeout(10000) });
      if (![200, 503].includes(response.status)) throw new Error("Unexpected status");
      setReport(await response.json());
    } catch { setReport({ status: "degraded", services: { api: "unavailable" } }); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void check(); }, [check]);
  return <main>
    <header><span className="brand">Solution Copilot</span><span>开发预览 · S00</span></header>
    <section><p className="eyebrow">从需求到方案，每一步都有依据</p><h1>方案工作台</h1>
      <p className="intro">项目正在初始化。客户与项目管理将在下一阶段接入。</p>
      <div className="health"><div className="heading"><h2>服务连接</h2><button onClick={check} disabled={loading}> {loading ? "检查中…" : "重新检查"}</button></div>
      <div role="status" aria-live="polite" aria-busy={loading}>
        <p>{loading ? "正在检查服务连接…" : report?.status === "ok" ? "基础服务已就绪" : "部分服务尚未就绪，请检查本地服务是否启动。"}</p>
        {!loading && report && <ul>{Object.entries(report.services).map(([key, value]) => <li key={key}><span>{labels[key] ?? key}</span><strong className={value === "ok" ? "ok" : "unavailable"}>{value === "ok" ? "已连接" : "未连接"}</strong></li>)}</ul>}
      </div></div>
    </section><footer>客户资料 · 结构化需求 · 可追溯方案</footer>
  </main>;
}
