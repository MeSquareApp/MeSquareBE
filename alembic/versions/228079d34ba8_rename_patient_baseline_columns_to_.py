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
    op.execute(
        "UPDATE patients SET baseline_height_cm = (baseline_height_cm * 12 + baseline_height_in) * 2.54"
    )
    op.execute("UPDATE patients SET baseline_weight_kg = baseline_weight_kg / 2.20462")

    # Drop the leftover imperial helper columns that no longer exist on the model.
    op.drop_column("patients", "baseline_height_in")
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
