import asyncio
import json
import aiosqlite
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

from app.jobs.models import JobRecord
from app.api.schemas import JobStatus

DB_PATH = Path("./data/jobs.db")

# Statuses considered "in-flight" — re-queue these on server restart
_IN_FLIGHT = {
    JobStatus.QUEUED,
    JobStatus.UPLOADING,
    JobStatus.ANALYZING,
    JobStatus.PLANNING,
    JobStatus.RENDERING,
}


class JobManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._db: Optional[aiosqlite.Connection] = None

    async def init(self):
        """Open the SQLite connection and create the jobs table if needed."""
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(DB_PATH))
        self._db.row_factory = aiosqlite.Row
        # WAL mode allows concurrent reads from the main process while the
        # worker subprocess is writing, avoiding SQLITE_BUSY errors.
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id          TEXT PRIMARY KEY,
                filename        TEXT NOT NULL,
                temp_path       TEXT,
                status          TEXT NOT NULL DEFAULT 'queued',
                progress        INTEGER NOT NULL DEFAULT 0,
                current_step    TEXT NOT NULL DEFAULT 'Queued',
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL,
                error           TEXT,
                raw_gcs_uri     TEXT,
                editing_plan    TEXT,
                output_gcs_uris TEXT NOT NULL DEFAULT '{}'
            )
        """)
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _row_to_record(self, row) -> JobRecord:
        return JobRecord(
            job_id=row["job_id"],
            filename=row["filename"],
            temp_path=Path(row["temp_path"]) if row["temp_path"] else None,
            status=JobStatus(row["status"]),
            progress=row["progress"],
            current_step=row["current_step"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            error=row["error"],
            raw_gcs_uri=row["raw_gcs_uri"],
            editing_plan=json.loads(row["editing_plan"]) if row["editing_plan"] else None,
            output_gcs_uris=json.loads(row["output_gcs_uris"]),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_job(self, job_id: str, filename: str, temp_path: Path) -> JobRecord:
        now = datetime.now(timezone.utc).isoformat()
        async with self._lock:
            await self._db.execute(
                """INSERT INTO jobs (job_id, filename, temp_path, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (job_id, filename, str(temp_path), now, now),
            )
            await self._db.commit()
        return await self.get_job(job_id)

    async def get_job(self, job_id: str) -> Optional[JobRecord]:
        async with self._db.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_record(row) if row else None

    async def update_job(self, job_id: str, **kwargs):
        if not kwargs:
            return
        now = datetime.now(timezone.utc).isoformat()

        # Serialize complex types for SQLite
        if "editing_plan" in kwargs and kwargs["editing_plan"] is not None:
            kwargs["editing_plan"] = json.dumps(kwargs["editing_plan"])
        if "output_gcs_uris" in kwargs:
            kwargs["output_gcs_uris"] = json.dumps(kwargs["output_gcs_uris"])
        if "status" in kwargs and isinstance(kwargs["status"], JobStatus):
            kwargs["status"] = kwargs["status"].value

        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [now, job_id]

        async with self._lock:
            await self._db.execute(
                f"UPDATE jobs SET {set_clause}, updated_at = ? WHERE job_id = ?",
                values,
            )
            await self._db.commit()

    async def list_jobs(self) -> list[JobRecord]:
        async with self._db.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC"
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_record(r) for r in rows]

    async def delete_job(self, job_id: str) -> bool:
        async with self._lock:
            cur = await self._db.execute(
                "DELETE FROM jobs WHERE job_id = ?", (job_id,)
            )
            await self._db.commit()
            return cur.rowcount > 0

    async def get_interrupted_jobs(self) -> list[JobRecord]:
        """Return jobs that were in-flight when the server last stopped."""
        placeholders = ",".join("?" for _ in _IN_FLIGHT)
        values = [s.value for s in _IN_FLIGHT]
        async with self._db.execute(
            f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY created_at ASC",
            values,
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_record(r) for r in rows]


# Module-level singleton
job_manager = JobManager()
