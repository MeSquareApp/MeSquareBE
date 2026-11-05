"""rename patient baseline columns to metric

Revision ID: 228079d34ba8
Revises: 3e59077034a7
Create Date: 2026-10-23 23:47:28.823565

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '228079d34ba8'
down_revision: Union[str, None] = '3e59077034a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check the live schema: the imperial helper columns were drift on the
    original development database and are not created by the migration chain,
    so they may or may not be present depending on the database's history."""
    inspector = sa.inspect(op.get_bind())
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


def upgrade() -> None:
    # The model now stores metric baselines: rename the imperial columns...
    op.alter_column("patients", "baseline_height_ft", new_column_name="baseline_height_cm")
    op.alter_column("patients", "baseline_weight_lbs", new_column_name="baseline_weight_kg")

    # The live height column was a smallint (drift from the original migrations):
    # widen it to double precision so fractional centimeters are not rounded away.
    op.alter_column(
        "patients",
        "baseline_height_cm",
        type_=sa.Double(),
        postgresql_using="baseline_height_cm::double precision",
    )

    # ...and convert the existing data. Height was stored as feet (baseline_height_ft)
    # plus an inches remainder (baseline_height_in, e.g. 6 ft + 1 in); weight in pounds.
    # The inches/age helper columns only ever existed through schema drift on the
    # development database, so convert/drop them only when present.
    if _column_exists("patients", "baseline_height_in"):
        op.execute(
            "UPDATE patients SET baseline_height_cm = (baseline_height_cm * 12 + baseline_height_in) * 2.54"
        )
        op.drop_column("patients", "baseline_height_in")
    op.execute("UPDATE patients SET baseline_weight_kg = baseline_weight_kg / 2.20462")
    if _column_exists("patients", "baseline_age"):
        op.drop_column("patients", "baseline_age")


def downgrade() -> None:
    # Restore the imperial representation. The inches remainder is derived from the
    # metric height; baseline_age is recomputed from date_of_birth.
    op.add_column("patients", sa.Column("baseline_height_in", sa.Double(), nullable=False, server_default="0"))
    op.add_column("patients", sa.Column("baseline_age", sa.Double(), nullable=False, server_default="0"))
    op.execute(
        """
        UPDATE patients SET
            baseline_height_in = MOD(ROUND(baseline_height_cm / 2.54)::int, 12),
            baseline_age = EXTRACT(YEAR FROM AGE(date_of_birth))::double precision,
            baseline_height_cm = FLOOR(baseline_height_cm / 2.54 / 12),
            baseline_weight_kg = baseline_weight_kg * 2.20462
        """
    )
    op.alter_column(
        "patients",
        "baseline_height_cm",
        type_=sa.SmallInteger(),
        postgresql_using="baseline_height_cm::smallint",
    )
    op.alter_column("patients", "baseline_height_cm", new_column_name="baseline_height_ft")
    op.alter_column("patients", "baseline_weight_kg", new_column_name="baseline_weight_lbs")
