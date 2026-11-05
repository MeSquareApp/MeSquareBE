import enum
import uuid
from datetime import date, datetime
from sqlalchemy import ARRAY, String, ForeignKey, DateTime, Enum, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.health import Twin, RawBiomarkerLog
    from app.models.associations import PatientPhysician, PhysicianClinic

class RoleEnum(str, enum.Enum):
    patient = "patient"
    physician = "physician"
    admin = "admin"


class User(Base):
    """Core identity and authentication table."""
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint(
            "auth0_issuer",
            "auth0_subject",
            name="uq_users_auth0_issuer_subject",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String)
    last_name: Mapped[str] = mapped_column(String)
    role: Mapped[RoleEnum] = mapped_column(Enum(RoleEnum))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    auth0_issuer: Mapped[str] = mapped_column(String)
    auth0_subject: Mapped[str] = mapped_column(String)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 1:1 Relationships mapped to the role entities
    patient: Mapped["Patient"] = relationship(back_populates="user", uselist=False)
    physician: Mapped["Physician"] = relationship(back_populates="user", uselist=False)
    admin: Mapped["Admin"] = relationship(back_populates="user", uselist=False)


class Patient(Base):
    """Patient-specific physiological constants.

    Only `date_of_birth` and `biological_sex` are collected at account
    creation; every other column stays NULL until the patient completes
    onboarding. NULL therefore means "not answered yet".
    """

    __tablename__ = "patients"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    date_of_birth: Mapped[date] = mapped_column()
    biological_sex: Mapped[str] = mapped_column(String)
    race: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    region: Mapped[str | None] = mapped_column(String, nullable=True)
    diagnosed_conditions: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    other_condition: Mapped[str | None] = mapped_column(String, nullable=True)
    current_medications: Mapped[str | None] = mapped_column(String, nullable=True)
    blood_pressure_medication: Mapped[str | None] = mapped_column(String, nullable=True)
    blood_pressure_details: Mapped[str | None] = mapped_column(String, nullable=True)
    cholesterol_medication: Mapped[str | None] = mapped_column(String, nullable=True)
    cholesterol_details: Mapped[str | None] = mapped_column(String, nullable=True)
    alcohol: Mapped[str | None] = mapped_column(String, nullable=True)
    smoking: Mapped[str | None] = mapped_column(String, nullable=True)
    recreational_drugs: Mapped[str | None] = mapped_column(String, nullable=True)
    exercise_hours: Mapped[str | None] = mapped_column(String, nullable=True)
    sleep_hours: Mapped[str | None] = mapped_column(String, nullable=True)
    high_blood_pressure_history: Mapped[str | None] = mapped_column(String, nullable=True)
    high_cholesterol_history: Mapped[str | None] = mapped_column(String, nullable=True)
    baseline_height_cm: Mapped[float | None] = mapped_column()
    baseline_weight_kg: Mapped[float | None] = mapped_column()
    waist_cm: Mapped[float | None] = mapped_column()
    allergies: Mapped[str | None] = mapped_column(String, nullable=True)
    medical_history: Mapped[str | None] = mapped_column(String, nullable=True)

    user: Mapped["User"] = relationship(back_populates="patient")
    twin: Mapped["Twin"] = relationship(back_populates="patient", uselist=False)
    physicians: Mapped[list["PatientPhysician"]] = relationship(back_populates="patient")
    biomarker_logs: Mapped[list["RawBiomarkerLog"]] = relationship(back_populates="patient")


class Physician(Base):
    """Physician-specific professional details.

    The row is created (empty) at account creation; license and specialty
    are provided when the physician completes onboarding. NULL means
    "not answered yet".
    """

    __tablename__ = "physicians"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    medical_license_number: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    specialty: Mapped[str | None] = mapped_column(String, nullable=True)

    user: Mapped["User"] = relationship(back_populates="physician")
    patients: Mapped[list["PatientPhysician"]] = relationship(back_populates="physician")
    clinics: Mapped[list["PhysicianClinic"]] = relationship(back_populates="physician")


class Admin(Base):
    """Platform administrator details."""
    __tablename__ = "admins"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    access_level: Mapped[str] = mapped_column(String)

    user: Mapped["User"] = relationship(back_populates="admin")