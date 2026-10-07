"""Generating the certificates of one job.

Each certificate is generated and committed on its own. If one fails, the error
is saved on that row and the loop moves on, so the rest of the job still
completes and progress is visible to the client while the job runs.
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Certificate, CertificateJob, CertificateStatus, JobStatus, utcnow
from app.services import storage
from app.services.certificate_pdf import CertificateData, render_certificate
from app.services.jobs import final_status, get_counts

logger = logging.getLogger(__name__)


def _generate_one(db: Session, job: CertificateJob, cert: Certificate) -> None:
    cert.attempts += 1
    try:
        path = storage.certificate_path(job.id, cert.id)
        render_certificate(path, CertificateData(
            recipient_name=cert.recipient_name,
            title=job.title,
            issued_by=job.issued_by,
            issued_on=job.issued_on,
            certificate_number=cert.certificate_number,
            achievement=cert.achievement,
        ))
        cert.status = CertificateStatus.GENERATED
        cert.file_path = str(path)
        cert.error = None
        cert.generated_at = utcnow()
    except Exception as exc:  # one bad certificate must not stop the job
        logger.exception("Certificate %s in job %s failed", cert.id, job.id)
        cert.status = CertificateStatus.FAILED
        cert.error = f"{type(exc).__name__}: {exc}"[:500]
    db.commit()


def process_job(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(CertificateJob, job_id)
        if job is None:
            logger.warning("Job %s no longer exists; skipping", job_id)
            return

        job.status = JobStatus.PROCESSING
        job.started_at = job.started_at or utcnow()
        db.commit()

        pending = db.scalars(
            select(Certificate)
            .where(Certificate.job_id == job.id, Certificate.status == CertificateStatus.PENDING)
            .order_by(Certificate.row_number)
        ).all()
        for cert in pending:
            _generate_one(db, job, cert)

        job.status = final_status(get_counts(db, job.id))
        job.finished_at = utcnow()
        db.commit()
        logger.info("Job %s finished with status %s", job.id, job.status.value)
