# StudioAgent

An autonomous AI video editing agent that converts raw talking-head videos into polished, social-media-ready content using **Gemini 2.5 Flash** and **FFmpeg/MoviePy**.

Upload a video → Gemini analyzes it → structured editing plan is generated → FFmpeg + MoviePy render the final 16:9 and 9:16 outputs automatically.

---

## Features

- **AI-powered analysis** — Gemini multimodal analysis of audio, visuals, and transcript
- **Automated editing plan** — scene cuts, zoom/speed effects, color grading, typography overlays
- **Subtitle generation** — SRT and ASS subtitles with styled formatting
- **Dual output** — 16:9 (YouTube/landscape) and 9:16 (Reels/Shorts/TikTok) rendered in one pass
- **Real-time progress** — WebSocket-based live progress bar in the web UI
- **Job persistence** — SQLite-backed job store, jobs survive server restarts
- **Non-blocking** — each video job runs in its own subprocess; the API stays responsive during processing
- **GCS integration** — optional upload to Google Cloud Storage with signed download URLs

---

## Architecture

```
Browser ──HTTP/WS──► FastAPI (main process)
                          │
                          ├── asyncio.Queue (job queue)
                          │
                          └── asyncio.create_subprocess_exec
                                    │
                                    └── app/worker_process.py  (per-job subprocess)
                                              │
                                              ├── Gemini Files API  (video analysis)
                                              ├── FFmpeg             (cuts, color, subtitles)
                                              └── MoviePy            (compositing, text, transitions)
```

SQLite (`data/jobs.db`) is the shared state between the main process and worker subprocesses.

---

## Requirements

- Python 3.11+
- FFmpeg on PATH (`ffmpeg --version` must work)
- A [Gemini API key](https://aistudio.google.com/app/apikey) (free tier is sufficient)

---

## Local Setup

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/StudioAgent.git
cd StudioAgent

# 2. Create and activate a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and set GEMINI_API_KEY

# 5. Run
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

Open `http://localhost:8080` in your browser.

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | Yes | — | Gemini API key from AI Studio |
| `GEMINI_MODEL` | No | `gemini-2.5-flash` | Gemini model ID |
| `GCP_PROJECT_ID` | No | — | GCP project (needed for GCS) |
| `GCS_BUCKET_NAME` | No | `studioagent-videos` | GCS bucket for output videos |
| `GOOGLE_APPLICATION_CREDENTIALS` | No | — | Path to service account JSON |
| `HOST` | No | `0.0.0.0` | Server bind host |
| `PORT` | No | `8080` | Server port |
| `TEMP_DIR` | No | `./tmp` | Directory for uploaded/processed files |
| `MAX_UPLOAD_SIZE_MB` | No | `500` | Max upload size in MB |
| `FFMPEG_PATH` | No | `ffmpeg` | Path to ffmpeg binary |

---

## Docker (local)

```bash
docker compose up --build
```

- App: `http://localhost:80` (via nginx) or `http://localhost:8080` (direct)
- Uploaded and rendered videos are stored in `./tmp` (bind-mounted)
- SQLite database is stored in `./data` (bind-mounted, persists across restarts)

---

## Deployment

### Railway (recommended — free tier)

Railway supports Docker, persistent volumes, and long-running processes — exactly what this app needs.

1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
3. Railway auto-detects the `Dockerfile`
4. Add environment variables in the Railway dashboard (copy from `.env.example`)
5. Add a **Volume** mounted at `/app/data` for SQLite persistence
6. Deploy

> **Why not Vercel?** Vercel is serverless with a 10–60s function timeout, no persistent filesystem, and restricted subprocess execution. Video processing takes several minutes and requires FFmpeg subprocesses — it's fundamentally incompatible.

### Render

1. Push to GitHub
2. New Web Service → select repo → **Docker** environment
3. Set env vars, add a **Disk** at `/app/data` (for SQLite)
4. Deploy

### Fly.io

```bash
fly launch          # auto-detects Dockerfile
fly secrets set GEMINI_API_KEY=your_key_here
fly volumes create studioagent_data --size 1  # persistent SQLite
fly deploy
```

### Google Cloud Run

Cloud Run is stateless (no persistent disk by default), so SQLite will reset on each deployment. For production use, mount a Cloud Filestore volume or switch to Cloud SQL.

```bash
gcloud builds submit --config cloudbuild.yaml
```

---

## API Reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/upload` | Upload a video file, returns `job_id` |
| `GET` | `/api/jobs` | List all jobs |
| `GET` | `/api/jobs/{job_id}` | Get job status and results |
| `GET` | `/api/jobs/{job_id}/download/{format}` | Download output (`16x9` or `9x16`) |
| `DELETE` | `/api/jobs/{job_id}` | Delete a job and its files |
| `WS` | `/ws/{job_id}` | WebSocket for real-time progress |

---

## Project Structure

```
app/
├── main.py               # FastAPI entry point, lifespan, startup
├── config.py             # Pydantic Settings (reads .env)
├── worker_process.py     # Subprocess entry point (one per job)
├── agent/
│   ├── analyzer.py       # Gemini multimodal video analysis
│   ├── planner.py        # Structured editing plan generation
│   ├── models.py         # EditingPlan Pydantic schema
│   └── prompts.py        # Gemini prompt templates
├── processing/
│   ├── pipeline.py       # Master orchestrator
│   ├── ffmpeg_engine.py  # Cuts, color grade, subtitle burn
│   ├── moviepy_engine.py # Compositing, overlays, transitions
│   ├── opencv_engine.py  # Scene detection, metadata extraction
│   ├── subtitle_engine.py# SRT / ASS generation
│   └── audio_engine.py   # Audio extraction and music mixing
├── jobs/
│   ├── manager.py        # SQLite job store (aiosqlite)
│   ├── worker.py         # asyncio.Queue + subprocess dispatcher
│   └── models.py         # JobRecord dataclass
├── api/
│   ├── routes.py         # All HTTP and WebSocket endpoints
│   └── schemas.py        # Request/response Pydantic models
├── storage/
│   └── gcs.py            # Google Cloud Storage integration
└── static/
    ├── index.html        # Web UI
    ├── style.css         # Dark theme
    └── app.js            # Upload, WebSocket progress, results
```

---

## License

MIT
