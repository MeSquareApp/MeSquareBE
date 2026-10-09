import enum
import uuid
from datetime import datetime
from sqlalchemy import ForeignKey, DateTime, Enum, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.users import Patient, Physician
    from app.models.clinics import Clinic

class AccessStatusEnum(str, enum.Enum):
    active = "active"
    revoked = "revoked"


class PatientPhysician(Base):
    """Junction table for the M:N Treats relationship."""
    __tablename__ = "patient_physicians"

    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.user_id"), primary_key=True)
    physician_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("physicians.user_id"), primary_key=True)
    status: Mapped[AccessStatusEnum] = mapped_column(Enum(AccessStatusEnum), default=AccessStatusEnum.active)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    patient: Mapped["Patient"] = relationship(back_populates="physicians")
    physician: Mapped["Physician"] = relationship(back_populates="patients")


class PhysicianClinic(Base):
    """Junction table for the M:N Works_at relationship."""
    __tablename__ = "physician_clinics"

    physician_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("physicians.user_id"), primary_key=True)
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clinics.id"), primary_key=True)

    physician: Mapped["Physician"] = relationship(back_populates="clinics")
    clinic: Mapped["Clinic"] = relationship(back_populates="physicians")