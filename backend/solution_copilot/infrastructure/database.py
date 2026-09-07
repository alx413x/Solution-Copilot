from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from solution_copilot.config import get_settings


@lru_cache
def get_engine():
    url = make_url(get_settings().database_url.get_secret_value()).set(
        drivername="postgresql+psycopg"
    )
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})


def get_session():
    with Session(get_engine()) as session:
        yield session
