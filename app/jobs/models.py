from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

from app.api.schemas import JobStatus


@dataclass
class JobRecord:
    job_id: str
    filename: str
    temp_path: Optional[Path] = None
    status: JobStatus = JobStatus.QUEUED
    progress: int = 0
    current_step: str = "Queued"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None
    raw_gcs_uri: Optional[str] = None
    editing_plan: Optional[dict] = None
    output_gcs_uris: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "progress": self.progress,
            "current_step": self.current_step,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "error": self.error,
            "editing_plan": self.editing_plan,
            "download_urls": self.output_gcs_uris if self.output_gcs_uris else None,
        }
