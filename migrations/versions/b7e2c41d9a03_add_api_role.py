# Alembic requires names like revision, and file names start with the revision id.
# Migrations repeat the same column definitions, which isn't duplicated logic.
# pylint: disable=invalid-name,duplicate-code
"""add the API's database role

Revision ID: b7e2c41d9a03
Revises: f403e88c0fdc
Create Date: 2026-11-14 05:10:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e2c41d9a03"
down_revision: Union[str, Sequence[str], None] = "f403e88c0fdc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE = "fplapi_app"

# Only what the API's queries need. The sync, migrations and the snapshot purge
# run in the workflows as postgres.
GRANTS = {
    "teams": "SELECT",
    "elements": "SELECT",
    "events": "SELECT",
    "fixtures": "SELECT",
    "element_event_points": "SELECT",
    "sync_runs": "SELECT",
    "profiles": "SELECT, INSERT, DELETE",
    "deleted_accounts": "SELECT, INSERT",
    "user_teams": "SELECT, INSERT, UPDATE, DELETE",
    "teams_tracked": "SELECT, INSERT, UPDATE",
    "notes": "SELECT, INSERT, UPDATE",
    "fpl_snapshots": "SELECT, INSERT, UPDATE",
}


def upgrade() -> None:
    """Upgrade schema."""
    # Roles are per server, not per database, so it may already exist. Its
    # password is set by hand in Supabase, never here.
    op.execute(f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE}') THEN
                CREATE ROLE {ROLE} LOGIN NOINHERIT;
            END IF;
        END $$
        """)
    # Above delete_account's Supabase timeout (8s), so a write waiting on its
    # advisory lock isn't cancelled.
    op.execute(f"ALTER ROLE {ROLE} SET statement_timeout = '10s'")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE}")
    for table, privileges in GRANTS.items():
        op.execute(f"GRANT {privileges} ON {table} TO {ROLE}")
        # RLS stays on for Supabase's Data API roles; grants limit the commands.
        op.execute(
            f"CREATE POLICY {ROLE} ON {table} FOR ALL TO {ROLE} "
            "USING (true) WITH CHECK (true)"
        )


def downgrade() -> None:
    """Downgrade schema."""
    # The role stays: dropping it would lock out a deployed API, and recreating
    # it means setting its password by hand again.
    for table in GRANTS:
        op.execute(f"DROP POLICY {ROLE} ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM {ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {ROLE}")
    op.execute(f"ALTER ROLE {ROLE} RESET statement_timeout")
