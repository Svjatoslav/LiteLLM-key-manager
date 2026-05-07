"""lead api keys

Revision ID: 0002_lead_api_keys
Revises: 0001_initial
Create Date: 2026-05-07 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_lead_api_keys"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("employee_keys", sa.Column("key_type", sa.String(length=40), nullable=False, server_default="Coding"))

    op.create_table(
        "lead_api_keys",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("team_id", sa.String(length=36), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lead_email", sa.String(length=320), nullable=False),
        sa.Column("litellm_user_id", sa.String(length=255), nullable=False),
        sa.Column("key_alias", sa.String(length=255), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column("masked_key", sa.String(length=80), nullable=False),
        sa.Column("litellm_token_id", sa.String(length=255), nullable=True),
        sa.Column("models_snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_lead_api_keys_team_id", "lead_api_keys", ["team_id"])
    op.create_index("ix_lead_api_keys_lead_email", "lead_api_keys", ["lead_email"])
    op.create_index("ix_lead_api_keys_litellm_user_id", "lead_api_keys", ["litellm_user_id"])
    op.create_index("ix_lead_api_keys_key_alias", "lead_api_keys", ["key_alias"])
    op.create_index("ix_lead_api_keys_token_hash", "lead_api_keys", ["token_hash"], unique=True)
    op.create_index("ix_lead_api_keys_litellm_token_id", "lead_api_keys", ["litellm_token_id"])
    op.create_index("ix_lead_api_keys_created_by_user_id", "lead_api_keys", ["created_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_lead_api_keys_created_by_user_id", table_name="lead_api_keys")
    op.drop_index("ix_lead_api_keys_litellm_token_id", table_name="lead_api_keys")
    op.drop_index("ix_lead_api_keys_token_hash", table_name="lead_api_keys")
    op.drop_index("ix_lead_api_keys_key_alias", table_name="lead_api_keys")
    op.drop_index("ix_lead_api_keys_litellm_user_id", table_name="lead_api_keys")
    op.drop_index("ix_lead_api_keys_lead_email", table_name="lead_api_keys")
    op.drop_index("ix_lead_api_keys_team_id", table_name="lead_api_keys")
    op.drop_table("lead_api_keys")
    op.drop_column("employee_keys", "key_type")
