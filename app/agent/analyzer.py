import json
import time
import logging
from pathlib import Path

from google.genai import types

from app.agent.client import get_genai_client
from app.agent.prompts import ANALYSIS_PROMPT
from app.config import Settings

logger = logging.getLogger(__name__)


async def analyze_video(video_path: Path, settings: Settings) -> dict:
    """
    Upload video to Gemini Files API, run multimodal analysis.
    Returns parsed analysis dict.
    """
    client = get_genai_client()

    # Step 1: Upload video to Gemini Files API
    logger.info(f"Uploading video to Gemini Files API: {video_path.name}")
    video_file = client.files.upload(file=str(video_path))

    # Step 2: Wait for file processing
    logger.info(f"Waiting for Gemini to process file: {video_file.name}")
    while video_file.state == "PROCESSING":
        time.sleep(5)
        video_file = client.files.get(name=video_file.name)

    if video_file.state == "FAILED":
        raise RuntimeError(f"Gemini file processing failed: {video_file.name}")

    logger.info(f"File processing complete. State: {video_file.state}")

    # Step 3: Call Gemini with video + analysis prompt
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=[
            ANALYSIS_PROMPT,
            video_file,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )

    # Step 4: Parse response
    analysis = json.loads(response.text)
    logger.info("Video analysis complete")

    # Step 5: Clean up uploaded file
    try:
        client.files.delete(name=video_file.name)
    except Exception:
        pass  # non-critical

    return analysis
