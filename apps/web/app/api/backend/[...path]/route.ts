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
    ![
      "customers",
      "projects",
      "documents",
      "jobs",
      "retrieval",
      "conversations",
      "clarifications",
      "runs",
      "memories",
      "messages",
      "solutions",
      "exports",
    ].includes(path[0]) ||
    path.some((p) => !/^[-a-zA-Z0-9]+$/.test(p))
  )
    return Response.json({}, { status: 404 });
  try {
    let body: Uint8Array<ArrayBuffer> | undefined;
    if (request.method !== "GET" && request.body) {
      const reader = request.body.getReader();
      const parts: Uint8Array[] = [];
      let length = 0;
      const limit =
        Number(process.env.UPLOAD_MAX_BYTES ?? 25 * 1024 * 1024) + 1024 * 1024;
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        length += value.length;
        if (length > limit) {
          await reader.cancel();
          return Response.json(
            { error: { message: "文件超过上传大小限制。" } },
            { status: 413 },
          );
        }
        parts.push(value);
      }
      body = new Uint8Array(length);
      let offset = 0;
      for (const part of parts) {
        body.set(part, offset);
        offset += part.length;
      }
    }
    const response = await upstream(
      path.join("/") + new URL(request.url).search,
      {
        method: request.method,
        headers: {
          ...(request.headers.get("Last-Event-ID")
            ? { "Last-Event-ID": request.headers.get("Last-Event-ID")! }
            : {}),
          "Content-Type":
            request.headers.get("Content-Type") ?? "application/json",
        },
        body,
      },
    );
    const headers = new Headers({
      "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
    });
    for (const key of ["Content-Type", "Content-Disposition"]) {
      const value = response.headers.get(key);
      if (value) headers.set(key, value);
    }
    return new Response(response.body, { status: response.status, headers });
  } catch {
    return unavailable();
  }
}
export { proxy as GET, proxy as POST, proxy as PATCH, proxy as DELETE };
