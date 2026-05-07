"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


team_role = postgresql.ENUM("lead", name="teamrole", create_type=False)
key_status = postgresql.ENUM("active", "blocked", "deleted", name="keystatus", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    team_role.create(bind, checkfirst=True)
    key_status.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "teams",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("litellm_team_id", sa.String(length=255), nullable=False),
        sa.Column("models", sa.JSON(), nullable=False),
        sa.Column("max_budget", sa.Float(), nullable=True),
        sa.Column("rpm_limit", sa.Integer(), nullable=True),
        sa.Column("tpm_limit", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_teams_slug", "teams", ["slug"], unique=True)
    op.create_index("ix_teams_litellm_team_id", "teams", ["litellm_team_id"], unique=True)

    op.create_table(
        "team_members",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("team_id", sa.String(length=36), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", team_role, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_member"),
    )
    op.create_index("ix_team_members_team_id", "team_members", ["team_id"])
    op.create_index("ix_team_members_user_id", "team_members", ["user_id"])

    op.create_table(
        "invites",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("team_id", sa.String(length=36), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_invites_token_hash", "invites", ["token_hash"], unique=True)
    op.create_index("ix_invites_email", "invites", ["email"])
    op.create_index("ix_invites_team_id", "invites", ["team_id"])
    op.create_index("ix_invites_created_by_user_id", "invites", ["created_by_user_id"])

    op.create_table(
        "employee_keys",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("team_id", sa.String(length=36), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_email", sa.String(length=320), nullable=False),
        sa.Column("owner_name", sa.String(length=200), nullable=False),
        sa.Column("purpose", sa.String(length=500), nullable=False),
        sa.Column("duration", sa.String(length=40), nullable=True),
        sa.Column("key_alias", sa.String(length=255), nullable=False),
        sa.Column("litellm_token_id", sa.String(length=255), nullable=True),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column("masked_key", sa.String(length=80), nullable=False),
        sa.Column("status", key_status, nullable=False),
        sa.Column("models_snapshot", sa.JSON(), nullable=False),
        sa.Column("limits_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rotated_from_key_id", sa.String(length=36), sa.ForeignKey("employee_keys.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_employee_keys_team_id", "employee_keys", ["team_id"])
    op.create_index("ix_employee_keys_owner_email", "employee_keys", ["owner_email"])
    op.create_index("ix_employee_keys_key_alias", "employee_keys", ["key_alias"])
    op.create_index("ix_employee_keys_litellm_token_id", "employee_keys", ["litellm_token_id"])
    op.create_index("ix_employee_keys_created_by_user_id", "employee_keys", ["created_by_user_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("actor_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("team_id", sa.String(length=36), sa.ForeignKey("teams.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.String(length=80), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("ip_address", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])
    op.create_index("ix_audit_events_team_id", "audit_events", ["team_id"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])

    op.create_table(
        "ad_group_mappings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("ad_group_dn", sa.String(length=512), nullable=False),
        sa.Column("team_id", sa.String(length=36), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=True),
        sa.Column("role", team_role, nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ad_group_mappings_ad_group_dn", "ad_group_mappings", ["ad_group_dn"], unique=True)
    op.create_index("ix_ad_group_mappings_team_id", "ad_group_mappings", ["team_id"])


def downgrade() -> None:
    op.drop_index("ix_ad_group_mappings_team_id", table_name="ad_group_mappings")
    op.drop_index("ix_ad_group_mappings_ad_group_dn", table_name="ad_group_mappings")
    op.drop_table("ad_group_mappings")
    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_index("ix_audit_events_team_id", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_user_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_employee_keys_created_by_user_id", table_name="employee_keys")
    op.drop_index("ix_employee_keys_litellm_token_id", table_name="employee_keys")
    op.drop_index("ix_employee_keys_key_alias", table_name="employee_keys")
    op.drop_index("ix_employee_keys_owner_email", table_name="employee_keys")
    op.drop_index("ix_employee_keys_team_id", table_name="employee_keys")
    op.drop_table("employee_keys")
    op.drop_index("ix_invites_created_by_user_id", table_name="invites")
    op.drop_index("ix_invites_team_id", table_name="invites")
    op.drop_index("ix_invites_email", table_name="invites")
    op.drop_index("ix_invites_token_hash", table_name="invites")
    op.drop_table("invites")
    op.drop_index("ix_team_members_user_id", table_name="team_members")
    op.drop_index("ix_team_members_team_id", table_name="team_members")
    op.drop_table("team_members")
    op.drop_index("ix_teams_litellm_team_id", table_name="teams")
    op.drop_index("ix_teams_slug", table_name="teams")
    op.drop_table("teams")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    key_status.drop(op.get_bind(), checkfirst=True)
    team_role.drop(op.get_bind(), checkfirst=True)
