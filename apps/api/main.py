from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from solution_copilot.application.errors import AppError
from solution_copilot.config import get_settings
from solution_copilot.infrastructure.health import HealthReport, readiness

from apps.api.conversations import router as conversations_router
from apps.api.customers import router
from apps.api.documents import router as documents_router
from apps.api.requirements import router as requirements_router
from apps.api.retrieval import router as retrieval_router
from apps.api.solutions import router as solutions_router
from apps.api.upload_limit import UploadLimit


@asynccontextmanager
async def lifespan(app):
    get_settings()  # Fail startup if production enables development authentication.
    yield


app = FastAPI(title="Solution Copilot API", version="0.2.0", lifespan=lifespan)
app.include_router(router)
app.include_router(conversations_router)
app.include_router(documents_router)
app.include_router(retrieval_router)
app.include_router(requirements_router)
app.include_router(solutions_router)
app.add_middleware(UploadLimit)


def error_response(status, code, message):
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": code, "message": message, "details": {}, "request_id": str(uuid4())}
        },
    )


@app.exception_handler(AppError)
async def app_error(request: Request, exc: AppError):
    return error_response(exc.status, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return error_response(422, "VALIDATION_ERROR", "输入格式不正确，请检查必填项和字段长度。")


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
