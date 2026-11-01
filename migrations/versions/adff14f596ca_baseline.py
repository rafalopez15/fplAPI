# Alembic requires names like revision, and file names start with the revision id.
# pylint: disable=invalid-name
"""baseline

Revision ID: adff14f596ca
Revises:
Create Date: 2026-11-01 10:41:59.418143

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = 'adff14f596ca'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Empty: this revision marks the starting point."""


def downgrade() -> None:
    """Downgrade schema."""
