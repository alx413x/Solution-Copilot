from fastapi import FastAPI, Response
from solution_copilot.infrastructure.health import HealthReport, readiness

app = FastAPI(title="Solution Copilot API", version="0.1.0")


@app.get("/api/v1/health/live")
def live() -> dict[str, str]:
    return {"status": "ok", "service": "api"}


@app.get(
    "/api/v1/health/ready", response_model=HealthReport, responses={503: {"model": HealthReport}}
)
def ready(response: Response) -> HealthReport:
    report = readiness()
    if report.status != "ok":
        response.status_code = 503
    return report
