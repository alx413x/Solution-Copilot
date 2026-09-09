import { cookies } from "next/headers";
export const cookieOptions = {
  httpOnly: true,
  sameSite: "strict" as const,
  secure: process.env.APP_ENV === "production",
  path: "/",
  maxAge: 28800,
};
export function sameOrigin(request: Request) {
  return (
    request.headers.get("origin") ===
    (process.env.WEB_ORIGIN ?? "http://127.0.0.1:3000")
  );
}
export async function upstream(
  path: string,
  init: RequestInit = {},
  token?: string,
) {
  const jar = await cookies();
  const headers = new Headers({
    "Content-Type":
      new Headers(init.headers).get("Content-Type") ?? "application/json",
  });
  const lastEventId = new Headers(init.headers).get("Last-Event-ID");
  if (lastEventId) headers.set("Last-Event-ID", lastEventId);
  const credential = token ?? jar.get("sc_token")?.value;
  if (credential) headers.set("Authorization", `Bearer ${credential}`);
  const org = jar.get("sc_org")?.value;
  if (org) headers.set("X-Organization-ID", org);
  return fetch(
    `${process.env.API_BASE_URL ?? "http://127.0.0.1:8000"}/api/v1/${path}`,
    {
      ...init,
      headers,
      cache: "no-store",
      signal: AbortSignal.timeout(60000),
      redirect: "error",
    },
  );
}
export function unavailable() {
  return Response.json(
    { error: { message: "服务暂时无法连接，请稍后重试。" } },
    { status: 503 },
  );
}
