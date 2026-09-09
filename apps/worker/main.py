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
    broker_connection_timeout=2,
)


@app.task(name="documents.parse", acks_late=True, reject_on_worker_lost=True)
def parse_document(job_id):
    from solution_copilot.application.document_jobs import run_job

    run_job(job_id)


@app.task(name="requirements.extract", acks_late=True, reject_on_worker_lost=True)
def extract_requirements(job_id):
    from solution_copilot.application.requirement_jobs import run_job

    run_job(job_id)


@app.task(name="system.check_infrastructure")
def check_infrastructure():
    report = readiness()
    if report.status != "ok":
        raise RuntimeError("Infrastructure unavailable")
    return report.model_dump()


@app.task(name="conversations.respond", acks_late=True, reject_on_worker_lost=True)
def respond_conversation(run_id):
    from solution_copilot.application.conversation_jobs import run_job

    run_job(run_id)
