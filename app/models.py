"""Database tables.

A CertificateJob is one bulk request. It owns one Certificate row per recipient,
and each row tracks its own status, so one bad recipient never hides the others.
"""
import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"  # every recipient got a certificate
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"  # some certificates generated, some did not
    FAILED = "FAILED"  # nothing could be generated


class CertificateStatus(str, enum.Enum):
    PENDING = "PENDING"  # valid, waiting to be generated
    GENERATED = "GENERATED"
    FAILED = "FAILED"  # valid data, but generation raised an error (can be retried)
    INVALID = "INVALID"  # rejected by validation, never generated


class CertificateJob(Base):
    __tablename__ = "certificate_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.QUEUED, index=True)

    # Certificate details shared by every recipient in the job.
    title: Mapped[str] = mapped_column(String(200))
    issued_on: Mapped[date] = mapped_column(Date)
    issued_by: Mapped[str] = mapped_column(String(120))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    certificates: Mapped[list["Certificate"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="Certificate.row_number"
    )


class Certificate(Base):
    __tablename__ = "certificates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("certificate_jobs.id"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)  # 1-based position in the request

    recipient_name: Mapped[str] = mapped_column(String(200), default="")
    recipient_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    achievement: Mapped[str | None] = mapped_column(String(200), nullable=True)

    certificate_number: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)
    status: Mapped[CertificateStatus] = mapped_column(
        Enum(CertificateStatus), default=CertificateStatus.PENDING, index=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped[CertificateJob] = relationship(back_populates="certificates")
