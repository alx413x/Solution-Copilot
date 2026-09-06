export async function GET() {
  try {
    const response = await fetch(`${process.env.API_BASE_URL ?? "http://127.0.0.1:8000"}/api/v1/health/ready`, {
      cache: "no-store", signal: AbortSignal.timeout(8000),
    });
    return Response.json(await response.json(), { status: response.status });
  } catch {
    return Response.json({ status: "degraded", services: { api: "unavailable" } }, { status: 503 });
  }
}
