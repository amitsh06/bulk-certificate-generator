# Bulk Certificate Generator

An API that creates certificates for many people at once.
You send a list of recipients. It checks each one, makes a PDF certificate for every valid recipient in the background, and lets you track progress and download the PDFs.

**Built with:** Python, FastAPI, SQLAlchemy (SQLite), ReportLab

![Sample certificate](docs/sample-certificate.png)

## Setup and run

Needs Python 3.10 or newer.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000/docs** to try every endpoint in the browser.

Settings such as the database URL and the storage folder can be changed in a `.env` file (see `.env.example`).

## Run the tests

```bash
pip install -r requirements-dev.txt
pytest
```

## How to use it

**1. Send the recipients.** This returns `202 Accepted` and a job `id` straight away.

```bash
curl -X POST http://127.0.0.1:8000/api/jobs -H "Content-Type: application/json" -d @samples/job.json
```

```json
{
  "title": "Drone Mapping Fundamentals Workshop",
  "issued_by": "Aereo Academy",
  "recipients": [
    {"name": "Jane Doe", "email": "jane@example.com", "achievement": "Grade: A"},
    {"name": "John Doe"}
  ]
}
```

You can also upload a CSV file to `POST /api/jobs/csv` (example: `samples/recipients.csv`).

**2. Check progress:** `GET /api/jobs/{id}`
Shows the status (`QUEUED` → `PROCESSING` → `COMPLETED`), the counts, and the percentage done.

**3. See each recipient's result:** `GET /api/jobs/{id}/certificates`
Each row is `GENERATED`, `INVALID` (with the reason, such as "name is required") or `FAILED` (with the error).

**4. Download:**
- One certificate: `GET /api/certificates/{id}/download`
- All of them as a ZIP: `GET /api/jobs/{id}/download`

**5. Retry failures:** `POST /api/jobs/{id}/retry` makes only the failed certificates again.

## How it works

1. The API saves the job and one row per recipient in the database, then replies immediately.
2. A background worker makes the PDFs one by one and saves each result as it goes.
3. The client checks the job status until it is finished, then downloads the PDFs.

```
app/
  main.py               start-up: creates tables, starts workers, resumes unfinished jobs
  api/routes.py         the endpoints
  models.py             database tables (jobs, certificates)
  schemas.py            request and response formats
  validation.py         checks on each recipient
  services/
    jobs.py             create jobs, count results, retry
    processor.py        makes the certificates for a job
    runner.py           runs jobs in the background
    certificate_pdf.py  the certificate template
tests/                  automated tests
```

## Design decisions

- **Background processing.** Big lists take time, so the API answers right away and does the work in the background. In a test run, a 500-recipient request was accepted in about 0.2 seconds, and all the PDFs were ready about 3 seconds later.
- **Bad rows don't block good ones.** A recipient with a missing name or a wrong email is marked `INVALID` with the reason, and everyone else still gets a certificate.
- **One failure doesn't stop the job.** Each certificate is made and saved separately. If one fails, only that one is marked `FAILED`, and it can be retried later.
- **Simple worker pool instead of Celery.** This avoids needing Redis or another server. All background work goes through one small class (`runner.py`), so switching to Celery later is easy.
- **Safe after a restart.** Unfinished jobs continue when the app starts again. PDFs are written to a temporary file first, so a crash never leaves a broken PDF behind.
- **SQLite by default.** Nothing extra to install. Any SQL database, such as PostgreSQL, works by changing `CERTGEN_DATABASE_URL`.

## Future scope

- Celery and Redis for running workers on many machines
- Cloud storage (for example S3) for the PDFs
- Fonts for Hindi and other scripts (these names are flagged as invalid for now)
- Emailing each certificate to its recipient
- A QR code on each certificate, with a public page to verify it

---

AI tools were allowed for this assignment. I used Claude while building it, and I understand and can explain every part of the code.
