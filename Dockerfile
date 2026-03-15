# ── Build stage: install Python deps ─────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim

# System FFmpeg (much faster than the imageio_ffmpeg Python bundle),
# OpenCV runtime libs, and Liberation fonts (Arial-compatible for overlays)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsm6 \
        libxext6 \
        libgl1-mesa-glx \
        fonts-liberation \
        fonts-open-sans \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -fv

WORKDIR /app

# Copy installed Python packages from builder stage
COPY --from=builder /install /usr/local

# Copy application source
COPY app/ ./app/

# Persistent directories (volume-mounted in production)
RUN mkdir -p /app/tmp /app/data

EXPOSE 8080

# Single worker — video processing runs in thread pool, not as separate processes
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--workers", "1", \
     "--log-level", "info"]
