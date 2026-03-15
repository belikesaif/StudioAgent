import logging
import os
from pathlib import Path
from datetime import timedelta

from google.cloud import storage

from app.config import Settings

logger = logging.getLogger(__name__)

_client: storage.Client | None = None
_bucket: storage.Bucket | None = None


def init_gcs_client(settings: Settings):
    global _client, _bucket
    # Propagate credentials path into os.environ so the Google SDK ADC flow finds it
    if settings.google_application_credentials:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = settings.google_application_credentials
    _client = storage.Client(project=settings.gcp_project_id or None)
    _bucket = _client.bucket(settings.gcs_bucket_name)
    logger.info(f"GCS client initialized for bucket: {settings.gcs_bucket_name}")


async def upload_to_gcs(
    local_path: Path, gcs_path: str, content_type: str | None = None,
) -> str:
    """Upload a local file to GCS. Returns gs:// URI."""
    if _bucket is None:
        raise RuntimeError("GCS client not initialized")
    blob = _bucket.blob(gcs_path)
    blob.upload_from_filename(str(local_path), content_type=content_type)
    uri = f"gs://{_bucket.name}/{gcs_path}"
    logger.info(f"Uploaded {local_path.name} to {uri}")
    return uri


async def download_from_gcs(gcs_path: str, local_path: Path) -> Path:
    """Download a GCS object to local disk."""
    if _bucket is None:
        raise RuntimeError("GCS client not initialized")
    blob = _bucket.blob(gcs_path)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    blob.download_to_filename(str(local_path))
    return local_path


def generate_signed_url(gcs_path: str, expiration_minutes: int = 60) -> str:
    """Generate a signed URL for downloading."""
    if _bucket is None:
        raise RuntimeError("GCS client not initialized")
    blob = _bucket.blob(gcs_path)
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=expiration_minutes),
        method="GET",
    )
