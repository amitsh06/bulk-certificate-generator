"""Request and response models (the API contract)."""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import CertificateStatus, JobStatus


# ---------- requests ----------

class RecipientIn(BaseModel):
    """One recipient. Fields are deliberately loose here: data-quality problems
    (blank name, bad email, duplicates) are checked per recipient in
    app/validation.py, so one bad row does not reject the whole request."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    name: str | None = Field(default=None, examples=["Jane Doe"])
    email: str | None = Field(default=None, examples=["jane@example.com"])
    achievement: str | None = Field(
        default=None, description="Optional extra line printed on the certificate", examples=["Grade: A"]
    )


class JobCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200, description="Course or event name",
                       examples=["Python for Data Science Bootcamp"])
    issued_by: str = Field(min_length=1, max_length=120, examples=["Aereo Academy"])
    issued_on: date | None = Field(default=None, description="Defaults to today")
    recipients: list[RecipientIn] = Field(min_length=1)


# ---------- responses ----------

class JobCounts(BaseModel):
    total: int
    pending: int
    generated: int
    failed: int
    invalid: int


class JobLinks(BaseModel):
    self: str
    certificates: str
    download: str | None = None


class JobSummary(BaseModel):
    id: str
    status: JobStatus
    title: str
    issued_by: str
    issued_on: date
    counts: JobCounts
    progress_percent: float = Field(description="Share of valid recipients that have been processed")
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    links: JobLinks


class CertificateOut(BaseModel):
    id: str
    row_number: int
    recipient_name: str
    recipient_email: str | None
    achievement: str | None
    status: CertificateStatus
    certificate_number: str | None
    error: str | None
    attempts: int
    generated_at: datetime | None
    download_url: str | None


class CertificatePage(BaseModel):
    items: list[CertificateOut]
    total: int
    limit: int
    offset: int


class RecipientError(BaseModel):
    row_number: int
    errors: list[str]


class RetryResult(BaseModel):
    job_id: str
    requeued: int
    status: JobStatus
