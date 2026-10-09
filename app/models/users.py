import enum
import uuid
from datetime import date, datetime
from sqlalchemy import String, ForeignKey, DateTime, Enum, func
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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String)
    last_name: Mapped[str] = mapped_column(String)
    username: Mapped[str] = mapped_column(String)
    role: Mapped[RoleEnum] = mapped_column(Enum(RoleEnum))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # 1:1 Relationships mapped to the role entities
    patient: Mapped["Patient"] = relationship(back_populates="user", uselist=False)
    physician: Mapped["Physician"] = relationship(back_populates="user", uselist=False)
    admin: Mapped["Admin"] = relationship(back_populates="user", uselist=False)


class Patient(Base):
    """Patient-specific physiological constants."""
    __tablename__ = "patients"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    date_of_birth: Mapped[date] = mapped_column()
    biological_sex: Mapped[str] = mapped_column(String)
    baseline_height_ft: Mapped[float] = mapped_column()
    baseline_weight_lbs: Mapped[float] = mapped_column()
    allergies: Mapped[str] = mapped_column(String)
    medical_conditions: Mapped[str] = mapped_column(String)

    user: Mapped["User"] = relationship(back_populates="patient")
    twin: Mapped["Twin"] = relationship(back_populates="patient", uselist=False)
    physicians: Mapped[list["PatientPhysician"]] = relationship(back_populates="patient")
    biomarker_logs: Mapped[list["RawBiomarkerLog"]] = relationship(back_populates="patient")


class Physician(Base):
    """Physician-specific professional details."""
    __tablename__ = "physicians"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    medical_license_number: Mapped[str] = mapped_column(String, unique=True)
    specialty: Mapped[str] = mapped_column(String)

    user: Mapped["User"] = relationship(back_populates="physician")
    patients: Mapped[list["PatientPhysician"]] = relationship(back_populates="physician")
    clinics: Mapped[list["PhysicianClinic"]] = relationship(back_populates="physician")


class Admin(Base):
    """Platform administrator details."""
    __tablename__ = "admins"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    access_level: Mapped[str] = mapped_column(String)

    user: Mapped["User"] = relationship(back_populates="admin")