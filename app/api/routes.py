import uuid
import asyncio

import aiofiles
from fastapi import APIRouter, UploadFile, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse

from app.config import get_settings, Settings
from app.api.schemas import UploadResponse, JobStatusResponse, JobListResponse, JobStatus
from app.jobs.manager import job_manager

router = APIRouter()


@router.post("/upload", response_model=UploadResponse)
async def upload_video(file: UploadFile):
    settings = get_settings()

    # Validate file extension
    if not file.filename:
        raise HTTPException(400, "No filename provided")
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in settings.allowed_extensions:
        raise HTTPException(400, f"Unsupported format: {ext}. Allowed: {settings.allowed_extensions}")

    # Generate job ID
    job_id = str(uuid.uuid4())

    # Save upload to temp dir (stream to disk in 1 MB chunks)
    temp_path = settings.temp_dir / job_id / file.filename
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(temp_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            await f.write(chunk)

    # Create persistent job record
    await job_manager.create_job(job_id, file.filename, temp_path)

    # Push to the worker queue (non-blocking)
    from app.jobs.worker import pipeline_worker
    await pipeline_worker.enqueue(job_id, temp_path, settings)

    return UploadResponse(job_id=job_id, status=JobStatus.QUEUED, message="Processing started")


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs():
    jobs = await job_manager.list_jobs()
    return JobListResponse(
        jobs=[
            JobStatusResponse(**j.to_dict())
            for j in jobs
        ]
    )


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = await job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job.to_dict()


@router.get("/jobs/{job_id}/plan")
async def get_job_plan(job_id: str):
    job = await job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.editing_plan is None:
        raise HTTPException(404, "Editing plan not yet available")
    return job.editing_plan


@router.get("/jobs/{job_id}/download/{format_key}")
async def download_video(job_id: str, format_key: str):
    job = await job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(400, "Job not completed yet")

    # Map format_key to GCS path
    format_map = {"16x9": "16:9", "9x16": "9:16"}
    aspect = format_map.get(format_key)
    if not aspect or aspect not in job.output_gcs_uris:
        raise HTTPException(404, f"Format '{format_key}' not available")

    gcs_uri = job.output_gcs_uris[aspect]

    # Generate signed URL and redirect
    try:
        from app.storage.gcs import generate_signed_url
        gcs_path = gcs_uri.replace(f"gs://{get_settings().gcs_bucket_name}/", "")
        signed_url = generate_signed_url(gcs_path)
        return RedirectResponse(url=signed_url)
    except Exception:
        # Fallback: try to serve from local temp dir
        from fastapi.responses import FileResponse
        local_path = get_settings().temp_dir / job_id / f"final_{format_key}.mp4"
        if local_path.exists():
            return FileResponse(
                path=str(local_path),
                media_type="video/mp4",
                filename=f"studioagent_{format_key}.mp4",
            )
        raise HTTPException(500, "Could not generate download URL")


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    deleted = await job_manager.delete_job(job_id)
    if not deleted:
        raise HTTPException(404, "Job not found")
    return {"message": "Job deleted"}


@router.websocket("/ws/{job_id}")
async def job_progress_ws(websocket: WebSocket, job_id: str):
    await websocket.accept()
    try:
        while True:
            job = await job_manager.get_job(job_id)
            if job is None:
                await websocket.send_json({"error": "Job not found"})
                break
            await websocket.send_json(job.to_dict())
            if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                break
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
