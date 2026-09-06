"""Live integration smoke: running API, Web, Redis and a real Celery worker."""

import json
from contextlib import closing
from uuid import uuid4

import httpx
from celery import Celery
from solution_copilot.config import get_settings
from solution_copilot.infrastructure.health import s3_client

for url in ["http://127.0.0.1:8000/api/v1/health/ready", "http://127.0.0.1:3000/api/health"]:
    response = httpx.get(url, timeout=15, trust_env=False)
    response.raise_for_status()
    assert response.json()["status"] == "ok"
    print(url, response.json())

# A transient RPC result verifies actual queued execution without introducing
# Redis-backed authoritative business state. Business jobs are deferred to S02.
probe = Celery("smoke", broker=get_settings().redis_url.get_secret_value(), backend="rpc://")
result = probe.send_task("system.check_infrastructure", ignore_result=False, expires=30)
report = result.get(timeout=30)
assert report["status"] == "ok", report
print("Worker -> PostgreSQL/pgvector, Redis, S3:", json.dumps(report))

key = f"_smoke/{uuid4()}.txt"
bucket = get_settings().s3_bucket
with closing(s3_client()) as client:
    try:
        client.put_object(Bucket=bucket, Key=key, Body=b"s00-private-storage")
        body = client.get_object(Bucket=bucket, Key=key)["Body"]
        try:
            assert body.read() == b"s00-private-storage"
        finally:
            body.close()
        response = httpx.get(
            f"{get_settings().s3_endpoint_url}/{bucket}/{key}", timeout=5, trust_env=False
        )
        assert response.status_code == 403, response.status_code
        print("Private storage round trip and anonymous access denial: passed")
    finally:
        client.delete_object(Bucket=bucket, Key=key)
