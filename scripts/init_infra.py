from contextlib import closing

import psycopg
from botocore.exceptions import ClientError
from solution_copilot.config import get_settings
from solution_copilot.infrastructure.health import s3_client

settings = get_settings()
with psycopg.connect(settings.database_url.get_secret_value()) as conn:
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
with closing(s3_client()) as client:
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except ClientError as error:
        if error.response["Error"]["Code"] not in {"404", "NoSuchBucket"}:
            raise
        client.create_bucket(Bucket=settings.s3_bucket)
print("pgvector and private bucket ready")
