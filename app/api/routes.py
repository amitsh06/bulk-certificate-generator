"""HTTP endpoints."""
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.csv_import import CsvFormatError, parse_recipients_csv
from app.database import get_db
from app.models import Certificate, CertificateJob, CertificateStatus
from app.schemas import CertificateOut, CertificatePage, JobCreate, JobSummary, RetryResult
from app.services import jobs, storage

router = APIRouter(prefix="/api")


def _get_job_or_404(db: Session, job_id: str) -> CertificateJob:
    job = db.get(CertificateJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found")
    return job


def _start_job(request: Request, db: Session, payload: JobCreate) -> JobSummary:
    try:
        job = jobs.create_job(db, payload)
    except jobs.TooManyRecipients as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except jobs.NoValidRecipients as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"message": str(exc), "recipients": [e.model_dump() for e in exc.errors]},
        ) from exc
    request.app.state.runner.submit(job.id)
    db.refresh(job)  # the job may already be finished when processing runs inline
    return jobs.job_summary(db, job)


@router.post("/jobs", response_model=JobSummary, status_code=status.HTTP_202_ACCEPTED,
             summary="Create a bulk certificate job from JSON")
def create_job(payload: JobCreate, request: Request, db: Session = Depends(get_db)):
    """Accepts many recipients in one request and returns immediately with the job id.
    Poll `GET /api/jobs/{id}` for progress."""
    return _start_job(request, db, payload)


@router.post("/jobs/csv", response_model=JobSummary, status_code=status.HTTP_202_ACCEPTED,
             summary="Create a bulk certificate job from a CSV upload")
async def create_job_from_csv(
    request: Request,
    file: UploadFile = File(..., description="CSV with columns name, email, achievement"),
    title: str = Form(...),
    issued_by: str = Form(...),
    issued_on: date | None = Form(None),
    db: Session = Depends(get_db),
):
    try:
        recipients = parse_recipients_csv(await file.read())
        payload = JobCreate(title=title, issued_by=issued_by, issued_on=issued_on, recipients=recipients)
    except CsvFormatError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.errors(include_url=False)) from exc
    return _start_job(request, db, payload)


@router.get("/jobs/{job_id}", response_model=JobSummary, summary="Job status and progress")
def get_job(job_id: str, db: Session = Depends(get_db)):
    return jobs.job_summary(db, _get_job_or_404(db, job_id))


@router.get("/jobs/{job_id}/certificates", response_model=CertificatePage,
            summary="Per-recipient results, optionally filtered by status")
def list_certificates(
    job_id: str,
    status_filter: CertificateStatus | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    _get_job_or_404(db, job_id)
    conditions = [Certificate.job_id == job_id]
    if status_filter is not None:
        conditions.append(Certificate.status == status_filter)
    total = db.scalar(select(func.count()).select_from(Certificate).where(*conditions))
    rows = db.scalars(
        select(Certificate).where(*conditions).order_by(Certificate.row_number).limit(limit).offset(offset)
    ).all()
    return CertificatePage(items=[jobs.certificate_out(c) for c in rows], total=total, limit=limit, offset=offset)


@router.get("/jobs/{job_id}/download", summary="Download all generated certificates as a ZIP")
def download_job_zip(job_id: str, db: Session = Depends(get_db)):
    job = _get_job_or_404(db, job_id)
    if job.status in jobs.ACTIVE_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Job is still running; try again when it has finished")
    generated = db.scalars(
        select(Certificate)
        .where(Certificate.job_id == job_id, Certificate.status == CertificateStatus.GENERATED)
        .order_by(Certificate.row_number)
    ).all()
    if not generated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="This job has no generated certificates")
    zip_path = storage.build_zip(generated)
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"certificates_{job_id[:8]}.zip",
        background=BackgroundTask(Path(zip_path).unlink, missing_ok=True),
    )


@router.post("/jobs/{job_id}/retry", response_model=RetryResult, status_code=status.HTTP_202_ACCEPTED,
             summary="Retry the certificates that failed during generation")
def retry_failed(job_id: str, request: Request, db: Session = Depends(get_db)):
    job = _get_job_or_404(db, job_id)
    if job.status in jobs.ACTIVE_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Job is still running")
    requeued = jobs.requeue_failed(db, job)
    if requeued == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="No failed certificates to retry")
    request.app.state.runner.submit(job.id)
    db.refresh(job)
    return RetryResult(job_id=job.id, requeued=requeued, status=job.status)


@router.get("/certificates/{certificate_id}", response_model=CertificateOut, summary="One certificate's details")
def get_certificate(certificate_id: str, db: Session = Depends(get_db)):
    cert = db.get(Certificate, certificate_id)
    if cert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Certificate {certificate_id} not found")
    return jobs.certificate_out(cert)


@router.get("/certificates/{certificate_id}/download", summary="Download one certificate PDF")
def download_certificate(certificate_id: str, db: Session = Depends(get_db)):
    cert = db.get(Certificate, certificate_id)
    if cert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Certificate {certificate_id} not found")
    if cert.status != CertificateStatus.GENERATED or not cert.file_path or not Path(cert.file_path).exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Certificate is not available (status: {cert.status.value})")
    return FileResponse(cert.file_path, media_type="application/pdf", filename=f"{cert.certificate_number}.pdf")
