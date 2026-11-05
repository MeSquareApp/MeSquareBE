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


def _label_exists(type_name: str, label: str) -> bool:
    """Check the live enum labels: the display-label enum only existed on the
    original development database; databases created from the migration chain
    already have the lowercase values, so the renames must be skipped there."""
    result = op.get_bind().execute(
        sa.text(
            "SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
            "WHERE t.typname = :type_name AND e.enumlabel = :label"
        ),
        {"type_name": type_name, "label": label},
    )
    return result.first() is not None


def _rename_value(type_name: str, old_label: str, new_label: str) -> None:
    if _label_exists(type_name, old_label):
        op.execute(f"ALTER TYPE {type_name} RENAME VALUE '{old_label}' TO '{new_label}'")


def upgrade() -> None:
    # The existing roleenum type was created with display labels
    # ('Patient', 'Medical Professional', 'Admin') while the model's RoleEnum
    # uses ('patient', 'physician', 'admin'). users.role is already a native
    # roleenum column, so renaming the labels in place fixes both the stored
    # data and the type. Databases created from the migration chain already
    # use the lowercase labels, so the renames are conditional.
    _rename_value("roleenum", "Patient", "patient")
    _rename_value("roleenum", "Medical Professional", "physician")
    _rename_value("roleenum", "Admin", "admin")


def downgrade() -> None:
    op.execute("ALTER TYPE roleenum RENAME VALUE 'patient' TO 'Patient'")
    op.execute("ALTER TYPE roleenum RENAME VALUE 'physician' TO 'Medical Professional'")
    op.execute("ALTER TYPE roleenum RENAME VALUE 'admin' TO 'Admin'")
