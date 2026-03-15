from pathlib import Path


def extract_video_metadata(video_path: Path) -> dict:
    """
    Extract duration, resolution, FPS and audio presence using ffprobe.
    Avoids codec compatibility issues — ffprobe reads container metadata
    without decoding frames, so HEVC, VP9, and any mobile format works.
    """
    import subprocess
    import json

    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams", "-show_format",
            str(video_path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {video_path.name}: {result.stderr[:300]}")

    data = json.loads(result.stdout)
    streams = data.get("streams", [])

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video_stream:
        raise RuntimeError(f"No video stream found in {video_path.name}")

    duration = float(data.get("format", {}).get("duration", 0))

    fps_str = video_stream.get("r_frame_rate", "30/1")
    try:
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) else 30.0
    except Exception:
        fps = 30.0

    return {
        "duration": round(duration, 2),
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "fps": round(fps, 2),
        "frame_count": int(fps * duration),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


def extract_keyframes(
    video_path: Path, output_dir: Path, interval_sec: float = 2.0
) -> list[Path]:
    """Extract one frame every N seconds. Requires cv2."""
    import cv2  # lazy import — only needed when called

    output_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        cap.release()
        return []

    interval_frames = max(1, int(fps * interval_sec))
    frames = []
    idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % interval_frames == 0:
            path = output_dir / f"frame_{idx:06d}.jpg"
            cv2.imwrite(str(path), frame)
            frames.append(path)
        idx += 1

    cap.release()
    return frames


def detect_scene_changes(video_path: Path, threshold: float = 30.0) -> list[float]:
    """Detect scene changes via frame difference. Requires cv2."""
    import cv2  # lazy import
    import numpy as np

    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        cap.release()
        return []

    prev_frame = None
    changes = []
    idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if prev_frame is not None:
            diff = cv2.absdiff(prev_frame, gray)
            mean_diff = np.mean(diff)
            if mean_diff > threshold:
                changes.append(round(idx / fps, 2))
        prev_frame = gray
        idx += 1

    cap.release()
    return changes


def detect_faces(frame_path: Path) -> list[dict]:
    """Detect faces in a frame. Requires cv2."""
    import cv2  # lazy import

    frame = cv2.imread(str(frame_path))
    if frame is None:
        return []

    h, w = frame.shape[:2]
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, 1.1, 4)

    return [
        {
            "x": (x + w_f / 2) / w,
            "y": (y + h_f / 2) / h,
            "width": w_f / w,
            "height": h_f / h,
        }
        for (x, y, w_f, h_f) in faces
    ]
