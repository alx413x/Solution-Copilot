from alembic import context
from solution_copilot.domain.models import Base
from solution_copilot.infrastructure.database import get_engine

if context.is_offline_mode():
    raise RuntimeError("Use an explicit database connection for migrations")
with get_engine().connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
