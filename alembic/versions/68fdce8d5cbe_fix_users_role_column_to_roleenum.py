"""fix users role column to roleenum

Revision ID: 68fdce8d5cbe
Revises: 228079d34ba8
Create Date: 2026-10-24 00:13:01.073569

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '68fdce8d5cbe'
down_revision: Union[str, None] = '228079d34ba8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The existing roleenum type was created with display labels
    # ('Patient', 'Medical Professional', 'Admin') while the model's RoleEnum
    # uses ('patient', 'physician', 'admin'). users.role is already a native
    # roleenum column, so renaming the labels in place fixes both the stored
    # data and the type.
    op.execute("ALTER TYPE roleenum RENAME VALUE 'Patient' TO 'patient'")
    op.execute("ALTER TYPE roleenum RENAME VALUE 'Medical Professional' TO 'physician'")
    op.execute("ALTER TYPE roleenum RENAME VALUE 'Admin' TO 'admin'")


def downgrade() -> None:
    op.execute("ALTER TYPE roleenum RENAME VALUE 'patient' TO 'Patient'")
    op.execute("ALTER TYPE roleenum RENAME VALUE 'physician' TO 'Medical Professional'")
    op.execute("ALTER TYPE roleenum RENAME VALUE 'admin' TO 'Admin'")
