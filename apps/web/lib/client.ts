import type { components } from "../../../packages/contracts/api";
export type Customer = components["schemas"]["CustomerOut"];
export type Project = components["schemas"]["ProjectOut"];
export type Page<T> = { items: T[]; next_cursor: string | null };
export type Session = {
  user: { id: string; display_name: string };
  organizations: {
    id: string;
    name: string;
    role: "owner" | "member" | "viewer";
  }[];
  organizationId: string;
};
export async function api<T>(
  path: string,
  method = "GET",
  data?: unknown,
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: data === undefined ? undefined : JSON.stringify(data),
    signal: AbortSignal.timeout(15000),
  });
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401 && !path.includes("session"))
      window.location.assign("/login");
    throw new Error(result.error?.message ?? "操作失败，请稍后重试。");
  }
  return result;
}
