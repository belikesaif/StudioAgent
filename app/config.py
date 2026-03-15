from pathlib import Path
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # GCP
    gcp_project_id: str = ""
    gcs_bucket_name: str = "studioagent-videos"
    google_application_credentials: str = ""
    google_credentials_b64: str = ""  # base64-encoded service account JSON for Railway/cloud

    # Server
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False

    # Processing
    temp_dir: Path = Path("./tmp")
    max_upload_size_mb: int = 500
    allowed_extensions: list[str] = ["mp4", "mov", "avi", "webm", "mkv"]

    # FFmpeg — auto-detected from imageio_ffmpeg bundle if not set in .env
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @model_validator(mode="after")
    def resolve_paths(self) -> "Settings":
        """Resolve temp_dir to absolute so subprocess paths never depend on cwd."""
        self.temp_dir = self.temp_dir.resolve()
        if self.ffmpeg_path == "ffmpeg":
            try:
                import imageio_ffmpeg
                self.ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            except Exception:
                pass  # leave as "ffmpeg" and let it surface naturally
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
