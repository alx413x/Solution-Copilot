from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from typing import Literal

import boto3
import psycopg
from botocore.config import Config
from pydantic import BaseModel
from redis import Redis

from solution_copilot.config import get_settings


class HealthReport(BaseModel):
    status: Literal["ok", "degraded"]
    services: dict[str, Literal["ok", "unavailable"]]


def s3_client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
        config=Config(connect_timeout=2, read_timeout=2, retries={"max_attempts": 0}),
    )


def check_postgres():
    with psycopg.connect(get_settings().database_url.get_secret_value(), connect_timeout=2) as conn:
        conn.execute("SELECT 1").fetchone()
        if not conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'").fetchone():
            raise RuntimeError("vector extension missing")


def check_redis():
    with Redis.from_url(
        get_settings().redis_url.get_secret_value(), socket_connect_timeout=2, socket_timeout=2
    ) as client:
        client.ping()


def check_storage():
    with closing(s3_client()) as client:
        client.head_bucket(Bucket=get_settings().s3_bucket)


def readiness() -> HealthReport:
    def probe(item):
        name, check = item
        try:
            check()
            return name, "ok"
        except Exception:
            # Never return connection strings, credentials or provider exceptions.
            return name, "unavailable"

    with ThreadPoolExecutor(max_workers=3) as pool:
        services = dict(
            pool.map(
                probe,
                [("postgres", check_postgres), ("redis", check_redis), ("storage", check_storage)],
            )
        )
    return HealthReport(
        status="ok" if all(v == "ok" for v in services.values()) else "degraded", services=services
    )
