from pydantic import BaseModel
from enum import Enum
from typing import Optional
from datetime import datetime


class JobStatus(str, Enum):
    UPLOADING = "uploading"
    QUEUED = "queued"
    ANALYZING = "analyzing"
    PLANNING = "planning"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"


class UploadResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: int
    current_step: str
    created_at: datetime
    updated_at: datetime
    error: Optional[str] = None
    editing_plan: Optional[dict] = None
    download_urls: Optional[dict[str, str]] = None


class JobListResponse(BaseModel):
    jobs: list[JobStatusResponse]
