"""S03 vectors and Chinese full-text index, model identity lives on every chunk."""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import TSVECTOR

revision = "a6e033104c11"
down_revision = "9094c79bd5c7"
branch_labels = depends_on = None


def upgrade():
    op.add_column("document_chunks", sa.Column("embedding", Vector(), nullable=True))
    op.add_column("document_chunks", sa.Column("embedding_profile", sa.String(200), nullable=True))
    op.add_column("document_chunks", sa.Column("search_vector", TSVECTOR(), nullable=True))
    op.create_index(
        "ix_chunks_search_vector", "document_chunks", ["search_vector"], postgresql_using="gin"
    )


def downgrade():
    op.drop_index("ix_chunks_search_vector", table_name="document_chunks")
    op.drop_column("document_chunks", "search_vector")
    op.drop_column("document_chunks", "embedding_profile")
    op.drop_column("document_chunks", "embedding")
