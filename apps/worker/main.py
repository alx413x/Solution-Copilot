from celery import Celery
from solution_copilot.config import get_settings
from solution_copilot.infrastructure.health import readiness

app = Celery(
    "solution_copilot", broker=get_settings().redis_url.get_secret_value(), backend="rpc://"
)
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
)


@app.task(name="system.check_infrastructure")
def check_infrastructure():
    report = readiness()
    if report.status != "ok":
        raise RuntimeError("Infrastructure unavailable")
    return report.model_dump()
