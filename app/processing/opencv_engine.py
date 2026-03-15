from pathlib import Path


def extract_video_metadata(video_path: Path) -> dict:
    """
    Extract duration, resolution, FPS and audio presence using MoviePy.
    Avoids a hard dependency on ffprobe (not bundled by imageio_ffmpeg).
    """
    from moviepy import VideoFileClip

    clip = VideoFileClip(str(video_path))
    try:
        metadata = {
            "duration": round(clip.duration, 2),
            "width": clip.w,
            "height": clip.h,
            "fps": round(clip.fps, 2),
            "frame_count": int(clip.fps * clip.duration),
            "has_audio": clip.audio is not None,
        }
    finally:
        clip.close()
    return metadata


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
