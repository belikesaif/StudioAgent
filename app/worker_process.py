"""
Pipeline worker subprocess entry point.

Run as:  python -m app.worker_process <job_id>

Each video job is executed in its own Python process so that CPU-intensive
MoviePy / FFmpeg work never touches the main FastAPI event loop or its GIL.
Progress is written to the shared SQLite database and the main process
reads it via WebSocket polling.
"""
import asyncio
import sys
from pathlib import Path


async def main(job_id: str) -> None:
    from app.config import get_settings
    from app.jobs.manager import job_manager
    from app.api.schemas import JobStatus

    settings = get_settings()
    settings.temp_dir.mkdir(parents=True, exist_ok=True)

    # Each subprocess gets its own SQLite connection
    await job_manager.init()

    # Mirror the same service initialisation done in main.py lifespan
    if settings.gemini_api_key:
        from app.agent.client import init_genai_client
        init_genai_client(settings)

    if settings.gcp_project_id:
        try:
            from app.storage.gcs import init_gcs_client
            init_gcs_client(settings)
        except Exception:
            pass

    # Fetch job metadata from DB
    job = await job_manager.get_job(job_id)
    if job is None:
        print(f"[worker] Job {job_id} not found in database", file=sys.stderr)
        await job_manager.close()
        sys.exit(1)

    if job.temp_path is None or not job.temp_path.exists():
        await job_manager.update_job(
            job_id,
            status=JobStatus.FAILED,
            error="Source video file not found",
        )
        await job_manager.close()
        sys.exit(1)

    from app.processing.pipeline import run_pipeline
    await run_pipeline(job_id, job.temp_path, settings)

    await job_manager.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.worker_process <job_id>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
