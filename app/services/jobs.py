"""Creating jobs and reading their state."""
from datetime import date

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Certificate, CertificateJob, CertificateStatus, JobStatus
from app.schemas import (
    CertificateOut,
    JobCounts,
    JobCreate,
    JobLinks,
    JobSummary,
    RecipientError,
)
from app.validation import check_recipients

ACTIVE_STATUSES = (JobStatus.QUEUED, JobStatus.PROCESSING)


class TooManyRecipients(Exception):
    def __init__(self, limit: int, received: int):
        super().__init__(f"A job can have at most {limit} recipients; received {received}.")


class NoValidRecipients(Exception):
    def __init__(self, errors: list[RecipientError]):
        super().__init__("None of the recipients passed validation.")
        self.errors = errors


def make_certificate_number(job: CertificateJob, row_number: int) -> str:
    # Readable and unique: issue date + start of the job id + row position.
    return f"CERT-{job.issued_on:%Y%m%d}-{job.id[:8].upper()}-{row_number:05d}"


def create_job(db: Session, payload: JobCreate) -> CertificateJob:
    """Validate the recipients and store the job with one row per recipient.

    Valid rows start as PENDING; invalid rows are stored as INVALID with their
    reasons, so the client can see exactly which rows were skipped and why.
    """
    limit = get_settings().max_recipients_per_job
    if len(payload.recipients) > limit:
        raise TooManyRecipients(limit, len(payload.recipients))

    checked = check_recipients(payload.recipients)
    if not any(row.is_valid for row in checked):
        raise NoValidRecipients([RecipientError(row_number=r.row_number, errors=r.errors) for r in checked])

    job = CertificateJob(title=payload.title, issued_by=payload.issued_by, issued_on=payload.issued_on or date.today())
    db.add(job)
    db.flush()  # assigns job.id, needed for certificate numbers

    for row in checked:
        db.add(Certificate(
            job_id=job.id,
            row_number=row.row_number,
            recipient_name=row.name,
            recipient_email=row.email,
            achievement=row.achievement,
            status=CertificateStatus.PENDING if row.is_valid else CertificateStatus.INVALID,
            error="; ".join(row.errors) or None,
            certificate_number=make_certificate_number(job, row.row_number) if row.is_valid else None,
        ))
    db.commit()
    return job


def get_counts(db: Session, job_id: str) -> JobCounts:
    rows = db.execute(
        select(Certificate.status, func.count()).where(Certificate.job_id == job_id).group_by(Certificate.status)
    ).all()
    by_status = {status: count for status, count in rows}
    return JobCounts(
        total=sum(by_status.values()),
        pending=by_status.get(CertificateStatus.PENDING, 0),
        generated=by_status.get(CertificateStatus.GENERATED, 0),
        failed=by_status.get(CertificateStatus.FAILED, 0),
        invalid=by_status.get(CertificateStatus.INVALID, 0),
    )


def final_status(counts: JobCounts) -> JobStatus:
    if counts.generated == 0:
        return JobStatus.FAILED
    if counts.failed or counts.invalid:
        return JobStatus.COMPLETED_WITH_ERRORS
    return JobStatus.COMPLETED


def job_summary(db: Session, job: CertificateJob) -> JobSummary:
    counts = get_counts(db, job.id)
    processable = counts.total - counts.invalid
    done = counts.generated + counts.failed
    progress = round(100 * done / processable, 1) if processable else 100.0
    base = f"/api/jobs/{job.id}"
    return JobSummary(
        id=job.id,
        status=job.status,
        title=job.title,
        issued_by=job.issued_by,
        issued_on=job.issued_on,
        counts=counts,
        progress_percent=progress,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        links=JobLinks(
            self=base,
            certificates=f"{base}/certificates",
            download=f"{base}/download" if job.status not in ACTIVE_STATUSES and counts.generated else None,
        ),
    )


def certificate_out(cert: Certificate) -> CertificateOut:
    return CertificateOut(
        id=cert.id,
        row_number=cert.row_number,
        recipient_name=cert.recipient_name,
        recipient_email=cert.recipient_email,
        achievement=cert.achievement,
        status=cert.status,
        certificate_number=cert.certificate_number,
        error=cert.error,
        attempts=cert.attempts,
        generated_at=cert.generated_at,
        download_url=f"/api/certificates/{cert.id}/download" if cert.status == CertificateStatus.GENERATED else None,
    )


def requeue_failed(db: Session, job: CertificateJob) -> int:
    """Move FAILED certificates back to PENDING so the job can run again."""
    result = db.execute(
        update(Certificate)
        .where(Certificate.job_id == job.id, Certificate.status == CertificateStatus.FAILED)
        .values(status=CertificateStatus.PENDING, error=None)
    )
    if result.rowcount:
        job.status = JobStatus.QUEUED
        job.finished_at = None
    db.commit()
    return result.rowcount


def unfinished_job_ids(db: Session) -> list[str]:
    """Jobs that were queued or mid-way when the server last stopped."""
    return list(db.scalars(select(CertificateJob.id).where(CertificateJob.status.in_(ACTIVE_STATUSES))))
