import { sameOrigin, unavailable, upstream } from "../../../../lib/server";
async function proxy(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  if (request.method !== "GET" && !sameOrigin(request))
    return Response.json(
      { error: { message: "请求来源无效。" } },
      { status: 403 },
    );
  const { path } = await context.params;
  if (
    !["customers", "projects"].includes(path[0]) ||
    path.some((p) => !/^[-a-zA-Z0-9]+$/.test(p))
  )
    return Response.json({}, { status: 404 });
  try {
    const response = await upstream(
      path.join("/") + new URL(request.url).search,
      {
        method: request.method,
        body: request.method === "GET" ? undefined : await request.text(),
      },
    );
    return Response.json(await response.json(), { status: response.status });
  } catch {
    return unavailable();
  }
}
export { proxy as GET, proxy as POST, proxy as PATCH, proxy as DELETE };
