"""Where certificate files live on disk, and building ZIP downloads."""
import re
import tempfile
import zipfile
from pathlib import Path

from app.config import get_settings
from app.models import Certificate


def certificate_path(job_id: str, certificate_id: str) -> Path:
    return get_settings().storage_dir / "certificates" / job_id / f"{certificate_id}.pdf"


def _safe_filename(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return slug[:60] or "recipient"


def build_zip(certificates: list[Certificate]) -> Path:
    """Write the given generated certificates into a temporary ZIP file.

    The caller is responsible for deleting the file after sending it.
    """
    handle = tempfile.NamedTemporaryFile(prefix="certificates_", suffix=".zip", delete=False)
    handle.close()
    with zipfile.ZipFile(handle.name, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for cert in certificates:
            if cert.file_path and Path(cert.file_path).exists():
                arcname = f"{cert.row_number:04d}_{_safe_filename(cert.recipient_name)}.pdf"
                archive.write(cert.file_path, arcname=arcname)
    return Path(handle.name)
