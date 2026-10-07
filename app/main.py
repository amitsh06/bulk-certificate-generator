"""FastAPI application entry point: `uvicorn app.main:app --reload`."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.config import get_settings
from app.database import SessionLocal, init_db
from app.services.jobs import unfinished_job_ids
from app.services.runner import JobRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("certgen")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    init_db()
    app.state.runner = JobRunner(settings.processing_mode, settings.worker_threads)

    # Resume jobs that were interrupted by a restart. Only PENDING certificates
    # are processed, so nothing that was already generated is redone.
    with SessionLocal() as db:
        for job_id in unfinished_job_ids(db):
            logger.info("Resuming unfinished job %s", job_id)
            app.state.runner.submit(job_id)

    yield
    app.state.runner.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Bulk Certificate Generator",
        version="1.0.0",
        description="Generate certificates for many recipients in one request, track progress, download the PDFs.",
        lifespan=lifespan,
    )
    app.include_router(router)

    @app.get("/health", tags=["meta"])
    def health():
        return {"status": "ok"}

    return app


app = create_app()
