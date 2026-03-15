import subprocess
import logging
from pathlib import Path

from app.agent.models import MusicDirective

logger = logging.getLogger(__name__)


def extract_audio(video_path: Path, work_dir: Path, ffmpeg_path: str = "ffmpeg") -> Path:
    """Extract audio track from video as WAV."""
    output = work_dir / "audio_original.wav"
    cmd = [
        ffmpeg_path, "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "2",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"Audio extraction failed: {result.stderr[:300]}")
    return output


def mix_background_music(
    voice_audio: Path,
    music_directive: MusicDirective,
    work_dir: Path,
    music_file: Path | None = None,
    ffmpeg_path: str = "ffmpeg",
) -> Path:
    """
    Mix voice audio with background music, applying volume ducking.
    If no music_file is provided, returns the voice audio as-is.
    """
    if music_file is None or not music_file.exists():
        return voice_audio

    output = work_dir / "audio_mixed.wav"

    # Build volume keyframe filter for the music track
    keyframes = music_directive.volume_keyframes
    if keyframes:
        conditions = []
        for i, kf in enumerate(keyframes):
            next_time = keyframes[i + 1].time if i + 1 < len(keyframes) else 99999
            conditions.append(f"between(t,{kf.time:.2f},{next_time:.2f})*{kf.volume:.2f}")
        volume_expr = "+".join(conditions)
        music_filter = f"volume='{volume_expr}'"
    else:
        music_filter = "volume=0.15"

    cmd = [
        ffmpeg_path, "-y",
        "-i", str(voice_audio),
        "-i", str(music_file),
        "-filter_complex",
        f"[1:a]{music_filter}[music];[0:a][music]amix=inputs=2:duration=first:dropout_transition=2[out]",
        "-map", "[out]",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        logger.warning(f"Music mixing failed, using voice only: {result.stderr[:200]}")
        return voice_audio
    return output
