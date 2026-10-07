import io
import time
import zipfile

from pypdf import PdfReader

from app.config import get_settings
from app.database import SessionLocal
from app.models import CertificateJob, JobStatus
from tests.conftest import job_payload

NAMES = ["Jane Doe", "John Doe", "Test User"]


# ---------- creating a job ----------

def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_create_job_generates_every_certificate(client):
    response = client.post("/api/jobs", json=job_payload(NAMES))

    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "COMPLETED"
    assert job["counts"] == {"total": 3, "pending": 0, "generated": 3, "failed": 0, "invalid": 0}
    assert job["progress_percent"] == 100.0
    assert job["links"]["download"] == f"/api/jobs/{job['id']}/download"


def test_issued_on_defaults_to_today(client):
    payload = job_payload(NAMES[:1])
    del payload["issued_on"]
    job = client.post("/api/jobs", json=payload).json()
    assert job["issued_on"] == time.strftime("%Y-%m-%d")


# ---------- validation ----------

def test_malformed_requests_are_rejected(client):
    assert client.post("/api/jobs", json=job_payload(NAMES, title="")).status_code == 422
    assert client.post("/api/jobs", json=job_payload([])).status_code == 422
    assert client.post("/api/jobs", json=job_payload(NAMES, recipients="not a list")).status_code == 422


def test_too_many_recipients_is_rejected(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_recipients_per_job", 2)
    response = client.post("/api/jobs", json=job_payload(NAMES))
    assert response.status_code == 422
    assert "at most 2" in response.json()["detail"]


def test_invalid_rows_are_skipped_while_valid_rows_are_generated(client):
    payload = job_payload([], recipients=[
        {"name": "Jane Doe", "email": "jane@example.com"},
        {"name": "   ", "email": "blank@example.com"},
        {"name": "John Doe", "email": "not-an-email"},
        {"name": "jane  doe", "email": "JANE@example.com"},  # same person again
        {"name": "12345"},
        {"name": "परीक्षण नाम"},  # script not covered by the certificate font
    ])
    job = client.post("/api/jobs", json=payload).json()

    assert job["status"] == "COMPLETED_WITH_ERRORS"
    assert job["counts"]["generated"] == 1
    assert job["counts"]["invalid"] == 5

    invalid = client.get(f"/api/jobs/{job['id']}/certificates", params={"status": "INVALID"}).json()
    errors = {row["row_number"]: row["error"] for row in invalid["items"]}
    assert errors[2] == "name is required"
    assert errors[3].startswith("email is invalid")
    assert errors[4] == "duplicate of row 1"
    assert errors[5] == "name must contain at least one letter"
    assert "cannot print" in errors[6]


def test_request_with_no_valid_recipients_returns_row_errors(client):
    payload = job_payload([], recipients=[{"name": ""}, {"name": "John", "email": "bad"}])
    response = client.post("/api/jobs", json=payload)

    assert response.status_code == 422
    rows = response.json()["detail"]["recipients"]
    assert [r["row_number"] for r in rows] == [1, 2]


# ---------- generation ----------

def test_certificate_pdf_contains_recipient_details(client):
    job = client.post("/api/jobs", json=job_payload(["Jane Doe"])).json()
    cert = client.get(f"/api/jobs/{job['id']}/certificates").json()["items"][0]

    response = client.get(cert["download_url"])

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    text = PdfReader(io.BytesIO(response.content)).pages[0].extract_text()
    assert "Jane Doe" in text
    assert "Python for Data Science Bootcamp" in text
    assert cert["certificate_number"] in text


def test_very_long_name_still_generates(client):
    long_name = "Test User With An Extremely Long Name Used Only To Check That The Certificate Layout Wraps"
    job = client.post("/api/jobs", json=job_payload([long_name])).json()
    assert job["counts"]["generated"] == 1


def test_one_failed_certificate_does_not_stop_the_job(client, monkeypatch):
    from app.services import processor

    real_render = processor.render_certificate

    def flaky_render(path, data):
        if data.recipient_name == "John Doe":
            raise OSError("disk full")
        return real_render(path, data)

    monkeypatch.setattr(processor, "render_certificate", flaky_render)
    job = client.post("/api/jobs", json=job_payload(NAMES)).json()

    assert job["status"] == "COMPLETED_WITH_ERRORS"
    assert job["counts"]["generated"] == 2
    assert job["counts"]["failed"] == 1
    failed = client.get(f"/api/jobs/{job['id']}/certificates", params={"status": "FAILED"}).json()["items"]
    assert failed[0]["recipient_name"] == "John Doe"
    assert failed[0]["error"] == "OSError: disk full"


def test_failed_certificates_can_be_retried(client, monkeypatch):
    from app.services import processor

    real_render = processor.render_certificate
    monkeypatch.setattr(processor, "render_certificate", lambda path, data: (_ for _ in ()).throw(OSError("boom")))
    job = client.post("/api/jobs", json=job_payload(NAMES)).json()
    assert job["status"] == "FAILED"

    monkeypatch.setattr(processor, "render_certificate", real_render)
    retry = client.post(f"/api/jobs/{job['id']}/retry")
    assert retry.status_code == 202
    assert retry.json()["requeued"] == 3

    job = client.get(f"/api/jobs/{job['id']}").json()
    assert job["status"] == "COMPLETED"
    certs = client.get(f"/api/jobs/{job['id']}/certificates").json()["items"]
    assert all(c["attempts"] == 2 for c in certs)


def test_retry_without_failures_is_a_conflict(client):
    job = client.post("/api/jobs", json=job_payload(NAMES)).json()
    assert client.post(f"/api/jobs/{job['id']}/retry").status_code == 409


# ---------- status and retrieval ----------

def test_certificate_list_supports_paging(client):
    job = client.post("/api/jobs", json=job_payload(NAMES)).json()
    page = client.get(f"/api/jobs/{job['id']}/certificates", params={"limit": 2, "offset": 1}).json()

    assert page["total"] == 3
    assert [c["recipient_name"] for c in page["items"]] == ["John Doe", "Test User"]


def test_zip_download_contains_every_generated_certificate(client):
    job = client.post("/api/jobs", json=job_payload(NAMES)).json()
    response = client.get(f"/api/jobs/{job['id']}/download")

    assert response.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(response.content)).namelist()
    assert names == ["0001_Jane_Doe.pdf", "0002_John_Doe.pdf", "0003_Test_User.pdf"]


def test_zip_download_waits_for_running_jobs(client):
    job = client.post("/api/jobs", json=job_payload(NAMES)).json()
    with SessionLocal() as db:
        db.get(CertificateJob, job["id"]).status = JobStatus.PROCESSING
        db.commit()
    assert client.get(f"/api/jobs/{job['id']}/download").status_code == 409


def test_unknown_ids_return_404(client):
    assert client.get("/api/jobs/does-not-exist").status_code == 404
    assert client.get("/api/certificates/does-not-exist/download").status_code == 404


def test_invalid_certificate_cannot_be_downloaded(client):
    payload = job_payload([], recipients=[{"name": "Jane Doe"}, {"name": ""}])
    job = client.post("/api/jobs", json=payload).json()
    invalid = client.get(f"/api/jobs/{job['id']}/certificates", params={"status": "INVALID"}).json()["items"][0]

    assert invalid["download_url"] is None
    assert client.get(f"/api/certificates/{invalid['id']}/download").status_code == 404


# ---------- CSV upload ----------

def test_csv_upload_creates_a_job(client):
    csv_bytes = "﻿Name,Email,Achievement\nJane Doe,jane@example.com,Grade: A\n\nJohn Doe,,\n".encode()
    response = client.post(
        "/api/jobs/csv",
        data={"title": "Drone Mapping Workshop", "issued_by": "Aereo"},
        files={"file": ("recipients.csv", csv_bytes, "text/csv")},
    )

    assert response.status_code == 202
    assert response.json()["counts"]["generated"] == 2


def test_csv_without_name_column_is_rejected(client):
    response = client.post(
        "/api/jobs/csv",
        data={"title": "Workshop", "issued_by": "Aereo"},
        files={"file": ("recipients.csv", b"email\na@example.com\n", "text/csv")},
    )
    assert response.status_code == 422
    assert "name" in response.json()["detail"]


# ---------- background processing ----------

def test_background_mode_processes_the_job_after_responding(background_client):
    response = background_client.post("/api/jobs", json=job_payload(NAMES * 10))
    assert response.status_code == 202
    job_id = response.json()["id"]

    deadline = time.time() + 30
    while time.time() < deadline:
        job = background_client.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in ("QUEUED", "PROCESSING"):
            break
        time.sleep(0.2)

    assert job["status"] == "COMPLETED_WITH_ERRORS"  # 20 of the 30 rows are duplicates
    assert job["counts"]["generated"] == 3
    assert job["counts"]["invalid"] == 27


def test_unfinished_jobs_resume_on_startup(tmp_path, monkeypatch):
    from tests.conftest import _make_client

    # First run: create a job but stop before it is processed.
    with _make_client(tmp_path, monkeypatch, "sync") as c:
        c.app.state.runner.submit = lambda job_id: None  # simulate a crash before processing
        job_id = c.post("/api/jobs", json=job_payload(NAMES)).json()["id"]
        assert c.get(f"/api/jobs/{job_id}").json()["status"] == "QUEUED"

    # Second run: the app picks the job up again during startup.
    with _make_client(tmp_path, monkeypatch, "sync") as c:
        assert c.get(f"/api/jobs/{job_id}").json()["status"] == "COMPLETED"
