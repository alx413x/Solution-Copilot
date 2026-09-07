"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Session } from "../lib/client";
export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const cache = useQueryClient();
  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => api<Session>("/api/session"),
  });
  const org = session.data?.organizations.find(
    (o) => o.id === session.data?.organizationId,
  );
  return (
    <main className="workspace">
      <header>
        <Link className="brand" href="/customers">
          Solution Copilot
        </Link>
        <nav aria-label="主导航">
          <Link
            aria-current={
              pathname.startsWith("/customers") ? "page" : undefined
            }
            href="/customers"
          >
            客户
          </Link>
          <Link
            aria-current={pathname.startsWith("/projects") ? "page" : undefined}
            href="/projects"
          >
            项目
          </Link>
          <Link href="/">服务状态</Link>
        </nav>
        <div className="account">
          {org ? (
            <>
              <span>
                {org.name} ·{" "}
                {{ owner: "管理员", member: "成员", viewer: "只读" }[
                  org.role
                ] ?? org.role}
              </span>
              <button
                onClick={async () => {
                  await api("/api/session", "DELETE");
                  cache.clear();
                  window.location.assign("/login");
                }}
              >
                退出
              </button>
            </>
          ) : (
            <Link href="/login">登录</Link>
          )}
        </div>
      </header>
      {session.error ? (
        <div className="notice" role="alert">
          {session.error.message} <Link href="/login">前往登录</Link>
        </div>
      ) : (
        children
      )}
    </main>
  );
}
export function useRole() {
  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => api<Session>("/api/session"),
  });
  return session.data?.organizations.find(
    (o) => o.id === session.data.organizationId,
  )?.role;
}
