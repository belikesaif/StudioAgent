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
            job_id = await self._queue.get()
            # Fire-and-forget: the task waits on the semaphore internally,
            # so the loop is immediately free to dequeue the next job.
            asyncio.create_task(self._run_subprocess(job_id))

    async def _run_subprocess(self, job_id: str):
        async with self._semaphore:
            logger.info(f"Spawning subprocess for job {job_id}")
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "app.worker_process", job_id,
                cwd=str(_PROJECT_ROOT),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            logger.info(f"Subprocess PID={proc.pid} for job {job_id}")

            # await proc.communicate() is async — the event loop stays free
            # to serve HTTP requests and WebSocket updates while the subprocess
            # does all the CPU/GPU work in its own process.
            _stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                err = stderr.decode(errors="replace")[-600:] if stderr else "unknown error"
                logger.error(f"Subprocess for job {job_id} exited {proc.returncode}: {err}")
                # Mark failed only if the subprocess didn't already do it
                from app.jobs.manager import job_manager
                from app.api.schemas import JobStatus
                job = await job_manager.get_job(job_id)
                if job and job.status not in (JobStatus.COMPLETED, JobStatus.FAILED):
                    await job_manager.update_job(
                        job_id,
                        status=JobStatus.FAILED,
                        error=f"Process exited {proc.returncode}: {err}",
                    )
            else:
                logger.info(f"Subprocess completed for job {job_id}")


# Module-level singleton
pipeline_worker = PipelineWorker()
