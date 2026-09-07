import { cookies } from "next/headers";
import {
  cookieOptions,
  sameOrigin,
  unavailable,
  upstream,
} from "../../../lib/server";
export async function GET() {
  try {
    const response = await upstream("me");
    const data = await response.json();
    const organizationId = (await cookies()).get("sc_org")?.value;
    return Response.json(
      { ...data, organizationId },
      { status: response.status },
    );
  } catch {
    return unavailable();
  }
}
export async function POST(request: Request) {
  if (!sameOrigin(request))
    return Response.json(
      { error: { message: "请求来源无效。" } },
      { status: 403 },
    );
  try {
    const { token, organizationId } = await request.json();
    if (
      token !== undefined &&
      (typeof token !== "string" || token.length < 16 || token.length > 3500)
    )
      return Response.json(
        { error: { message: "请输入有效的访问凭据。" } },
        { status: 422 },
      );
    const response = await upstream("me", {}, token);
    const data = await response.json();
    if (!response.ok) return Response.json(data, { status: response.status });
    const org = organizationId ?? data.organizations[0]?.id;
    if (!data.organizations.some((item: { id: string }) => item.id === org))
      return Response.json(
        { error: { message: "无权访问该组织。" } },
        { status: 403 },
      );
    const jar = await cookies();
    if (token) jar.set("sc_token", token, cookieOptions);
    jar.set("sc_org", org, cookieOptions);
    return Response.json({ ok: true });
  } catch {
    return unavailable();
  }
}
export async function DELETE(request: Request) {
  if (!sameOrigin(request)) return Response.json({}, { status: 403 });
  const jar = await cookies();
  jar.delete("sc_token");
  jar.delete("sc_org");
  return Response.json({ ok: true });
}
