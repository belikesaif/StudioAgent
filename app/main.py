import base64
import logging
import os
import tempfile
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware


def _bootstrap_gcp_credentials() -> None:
    """Decode GOOGLE_CREDENTIALS_B64 → write to a temp file → set GOOGLE_APPLICATION_CREDENTIALS.
    This lets Railway/Render/Fly.io receive the service-account JSON as an env var."""
    b64 = os.environ.get("GOOGLE_CREDENTIALS_B64")
    if not b64:
        return
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return  # already set (e.g. local bind-mount)
    data = base64.b64decode(b64)
    tmp = tempfile.NamedTemporaryFile(
        delete=False, suffix=".json", prefix="gcp_sa_"
    )
    tmp.write(data)
    tmp.flush()
    tmp.close()
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = tmp.name


_bootstrap_gcp_credentials()

from app.config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.temp_dir.mkdir(parents=True, exist_ok=True)

    # 1. Open SQLite job store
    from app.jobs.manager import job_manager
    await job_manager.init()

    # 2. Start the pipeline worker queue
    from app.jobs.worker import pipeline_worker
    pipeline_worker.start()

    # 3. Re-queue any jobs interrupted by a previous server restart
    interrupted = await job_manager.get_interrupted_jobs()
    if interrupted:
        logger.warning(f"Recovering {len(interrupted)} interrupted job(s)")
        for job in interrupted:
            if job.temp_path and job.temp_path.exists():
                await job_manager.update_job(
                    job.job_id,
                    status="queued",
                    progress=0,
                    current_step="Re-queued after server restart",
                )
                await pipeline_worker.enqueue(job.job_id, job.temp_path, settings)
            else:
                # Source file is gone — mark as failed so the UI shows it
                await job_manager.update_job(
                    job.job_id,
                    status="failed",
                    error="Source file missing after server restart",
                )

    # 4. Initialize GenAI client
    if settings.gemini_api_key:
        from app.agent.client import init_genai_client
        init_genai_client(settings)

    # 5. Initialize GCS client
    if settings.gcp_project_id:
        from app.storage.gcs import init_gcs_client
        init_gcs_client(settings)

    yield

    # Shutdown — close the DB connection cleanly
    await job_manager.close()


app = FastAPI(title="StudioAgent", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.routes import router  # noqa: E402 — after app creation to avoid circular imports
app.include_router(router, prefix="/api")
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
async def root():
    return FileResponse("app/static/index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return RedirectResponse(url="/static/favicon.svg")
