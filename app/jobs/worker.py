"""
Async pipeline worker.

Each job is executed as a separate Python subprocess so that CPU-heavy
MoviePy and FFmpeg work runs in a separate GIL, keeping the FastAPI
event loop fully responsive for HTTP requests and WebSocket updates.

The main process only does:  await proc.communicate()  — which is async
and yields the event loop while the subprocess does all the real work.
"""
import asyncio
import logging
import sys
from pathlib import Path

from app.config import Settings

logger = logging.getLogger(__name__)

# Maximum number of video jobs running simultaneously.
# Each job can use 1–2 GB RAM; raise only if the server has ≥8 GB.
MAX_CONCURRENT = 1

# Kill a subprocess if it hasn't finished within this many seconds (15 min).
_SUBPROCESS_TIMEOUT = 900

# Resolve the project root once at import time (three levels up from this file:
# worker.py → jobs/ → app/ → project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class PipelineWorker:
    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        self._loop_task: asyncio.Task | None = None

    def start(self):
        """Start the background dispatch loop. Call once on app startup."""
        self._loop_task = asyncio.create_task(self._dispatch_loop())
        logger.info(f"Pipeline worker started (max_concurrent={MAX_CONCURRENT})")

    async def enqueue(self, job_id: str, video_path: Path, settings: Settings):
        """Add a job to the queue. Returns immediately."""
        # The subprocess reads the video path and settings from SQLite / .env,
        # so we only need to pass the job_id.
        await self._queue.put(job_id)
        logger.info(f"Enqueued job {job_id} (queue depth={self._queue.qsize()})")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _dispatch_loop(self):
        """Pull job IDs from the queue and spawn a subprocess for each."""
        while True:
            try:
                job_id = await self._queue.get()
                asyncio.create_task(self._run_subprocess(job_id))
            except Exception:
                logger.exception("Dispatch loop iteration failed — continuing")

    async def _run_subprocess(self, job_id: str):
        try:
            async with self._semaphore:
                logger.info(f"Spawning subprocess for job {job_id}")
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, "-m", "app.worker_process", job_id,
                    cwd=str(_PROJECT_ROOT),
                    # Inherit stdout/stderr so all subprocess logs appear in Railway/Docker logs
                    stdout=None,
                    stderr=None,
                )
                logger.info(f"Subprocess PID={proc.pid} for job {job_id}")

                try:
                    await asyncio.wait_for(proc.wait(), timeout=_SUBPROCESS_TIMEOUT)
                except asyncio.TimeoutError:
                    logger.error(
                        f"Subprocess for job {job_id} timed out after "
                        f"{_SUBPROCESS_TIMEOUT}s — killing PID {proc.pid}"
                    )
                    proc.kill()
                    await proc.wait()

                if proc.returncode != 0:
                    logger.error(f"Subprocess for job {job_id} exited {proc.returncode}")
                    # Subprocess writes its own error to DB; only mark failed if it didn't
                    from app.jobs.manager import job_manager
                    from app.api.schemas import JobStatus
                    job = await job_manager.get_job(job_id)
                    if job and job.status not in (JobStatus.COMPLETED, JobStatus.FAILED):
                        await job_manager.update_job(
                            job_id,
                            status=JobStatus.FAILED,
                            error=f"Worker process exited with code {proc.returncode} — check server logs",
                        )
                else:
                    logger.info(f"Subprocess completed for job {job_id}")
        except Exception:
            logger.exception(f"_run_subprocess failed for job {job_id}")
            try:
                from app.jobs.manager import job_manager
                from app.api.schemas import JobStatus
                await job_manager.update_job(
                    job_id,
                    status=JobStatus.FAILED,
                    error="Internal worker error — check server logs",
                )
            except Exception:
                logger.exception(f"Failed to mark job {job_id} as failed")


# Module-level singleton
pipeline_worker = PipelineWorker()
