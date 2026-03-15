import subprocess
import logging
from pathlib import Path

from app.agent.models import Scene, ActionType, ColorGradeParams, OutputFormat

logger = logging.getLogger(__name__)


class FFmpegEngine:
    def __init__(self, source_video: Path, work_dir: Path, settings):
        self.source = source_video
        self.work_dir = work_dir
        self.ffmpeg = settings.ffmpeg_path
        self.ffprobe = settings.ffprobe_path

    def _run(self, cmd: list[str]) -> subprocess.CompletedProcess:
        """Execute an FFmpeg command, raising on failure."""
        logger.info(f"FFmpeg cmd: {' '.join(str(c) for c in cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            # FFmpeg prints its version banner first; the real error is at the *end*
            error_tail = result.stderr[-2000:] if result.stderr else "no stderr"
            logger.error(f"FFmpeg stderr tail:\n{error_tail}")
            raise RuntimeError(f"FFmpeg failed (exit {result.returncode}): {error_tail}")
        return result

    # Shared x264 params to limit encoder memory on constrained containers.
    # rc-lookahead=10 (vs default 30) and ref=1 (vs default 2-3) slash the
    # frame-buffer footprint with minimal quality impact at -preset fast.
    _X264_LOW_MEM = "rc-lookahead=10:ref=1"

    def execute_cuts(self, scenes: list[Scene]) -> list[Path]:
        """Cut the source video into segments based on scene boundaries.
        Scales down to max 1280px (~720p) at this stage to cap memory usage
        for high-res inputs on constrained servers."""
        segments = []
        for i, scene in enumerate(scenes):
            # Skip scenes that are entirely cut
            if any(
                a.action_type == ActionType.CUT
                and a.start_time == scene.start_time
                and a.end_time == scene.end_time
                for a in scene.actions
            ):
                continue

            output = self.work_dir / f"segment_{i:03d}.mp4"
            duration = scene.end_time - scene.start_time
            cmd = [
                self.ffmpeg, "-y",
                "-ss", f"{scene.start_time:.3f}",
                "-i", str(self.source),
                "-t", f"{duration:.3f}",
                # Scale to max 1280px on longest side; never upscale; ensure even dims
                "-vf", "scale=1280:1280:force_original_aspect_ratio=decrease:force_divisible_by=2",
                "-c:v", "libx264", "-preset", "fast", "-threads", "2",
                "-x264-params", self._X264_LOW_MEM,
                "-c:a", "aac",
                "-movflags", "+faststart",
                str(output),
            ]
            self._run(cmd)

            # Validate the segment file is non-trivial (at least 4 KiB)
            if not output.exists() or output.stat().st_size < 4096:
                raise RuntimeError(
                    f"Segment {output.name} is missing or too small "
                    f"({output.stat().st_size if output.exists() else 0} bytes)"
                )
            segments.append(output)

        return segments

    def apply_speed_changes(self, segments: list[Path], scenes: list[Scene]) -> list[Path]:
        """Apply speed-up or slow-motion to individual segments."""
        results = []
        kept_scene_idx = 0

        for scene in scenes:
            # Skip cut scenes
            if any(
                a.action_type == ActionType.CUT
                and a.start_time == scene.start_time
                and a.end_time == scene.end_time
                for a in scene.actions
            ):
                continue

            if kept_scene_idx >= len(segments):
                break

            seg_path = segments[kept_scene_idx]
            speed_actions = [
                a for a in scene.actions
                if a.action_type in (ActionType.SLOW_MOTION, ActionType.SPEED_UP)
                and a.speed_params is not None
            ]

            if not speed_actions:
                results.append(seg_path)
                kept_scene_idx += 1
                continue

            factor = speed_actions[0].speed_params.factor
            output = self.work_dir / f"{seg_path.stem}_speed.mp4"

            video_filter = f"setpts={1/factor:.4f}*PTS"
            atempo_filters = self._build_atempo_chain(factor)

            cmd = [
                self.ffmpeg, "-y",
                "-i", str(seg_path),
                "-filter:v", video_filter,
                "-filter:a", atempo_filters,
                "-c:v", "libx264", "-preset", "fast", "-threads", "2",
                "-x264-params", self._X264_LOW_MEM,
                "-movflags", "+faststart",
                str(output),
            ]
            self._run(cmd)
            results.append(output)
            kept_scene_idx += 1

        return results

    def _build_atempo_chain(self, factor: float) -> str:
        """FFmpeg atempo only supports 0.5-2.0, so chain for wider ranges."""
        filters = []
        remaining = factor
        while remaining > 2.0:
            filters.append("atempo=2.0")
            remaining /= 2.0
        while remaining < 0.5:
            filters.append("atempo=0.5")
            remaining /= 0.5
        filters.append(f"atempo={remaining:.4f}")
        return ",".join(filters)

    def apply_color_grade(self, video_path: Path, grade: ColorGradeParams | None) -> Path:
        """Apply color grading via FFmpeg eq filter."""
        if grade is None:
            return video_path

        # Clamp to safe ranges — AI may generate values that exceed bounds
        brightness = max(-0.5, min(0.5, grade.brightness))
        contrast   = max(0.5,  min(2.0, grade.contrast))
        saturation = max(0.0,  min(3.0, grade.saturation))
        temperature = max(-0.5, min(0.5, getattr(grade, "temperature", 0.0)))

        # Skip the extra encode pass if values are all effectively neutral
        NEUTRAL = (
            abs(brightness) < 0.01
            and abs(contrast - 1.0) < 0.02
            and abs(saturation - 1.0) < 0.02
            and abs(temperature) < 0.01
        )
        if NEUTRAL:
            return video_path

        output = self.work_dir / f"{video_path.stem}_graded.mp4"

        filters = [
            f"eq=brightness={brightness:.3f}"
            f":contrast={contrast:.3f}"
            f":saturation={saturation:.3f}"
        ]

        # Approximate temperature via RGB channel multipliers
        if abs(temperature) >= 0.01:
            if temperature > 0:
                # Warmer: boost R, reduce B slightly
                r = 1.0 + temperature * 0.3
                b = 1.0 - temperature * 0.2
            else:
                # Cooler: boost B, reduce R slightly
                r = 1.0 + temperature * 0.2
                b = 1.0 - temperature * 0.3
            filters.append(
                f"colorchannelmixer=rr={r:.3f}:bb={b:.3f}"
            )

        vf = ",".join(filters)
        cmd = [
            self.ffmpeg, "-y",
            "-i", str(video_path),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-threads", "2",
            "-x264-params", self._X264_LOW_MEM,
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(output),
        ]
        self._run(cmd)
        return output

    def crop_to_vertical(self, input_path: Path, output_path: Path, fmt: OutputFormat):
        """Crop a 16:9 video to 9:16 using the specified crop region."""
        if fmt.crop_region:
            cr = fmt.crop_region
            crop_filter = (
                f"crop=iw*{cr.width:.4f}:ih*{cr.height:.4f}"
                f":iw*{cr.x:.4f}:ih*{cr.y:.4f},"
                f"scale={fmt.resolution[0]}:{fmt.resolution[1]}"
            )
        else:
            crop_filter = (
                f"crop=ih*9/16:ih:(iw-ih*9/16)/2:0,"
                f"scale={fmt.resolution[0]}:{fmt.resolution[1]}"
            )

        cmd = [
            self.ffmpeg, "-y",
            "-i", str(input_path),
            "-vf", crop_filter,
            "-c:v", "libx264", "-preset", "fast", "-threads", "2",
            "-x264-params", self._X264_LOW_MEM,
            "-c:a", "copy",
            str(output_path),
        ]
        self._run(cmd)

    def burn_subtitles(self, video_path: Path, ass_path: Path, output_path: Path):
        """Burn ASS subtitles into the video."""
        # Escape path for FFmpeg filter (Windows colons and backslashes)
        ass_escaped = str(ass_path).replace("\\", "/").replace(":", "\\:")
        cmd = [
            self.ffmpeg, "-y",
            "-i", str(video_path),
            "-vf", f"ass={ass_escaped}",
            "-c:v", "libx264", "-preset", "fast", "-threads", "2",
            "-x264-params", self._X264_LOW_MEM,
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ]
        self._run(cmd)

    def resize_video(self, input_path: Path, output_path: Path, width: int, height: int):
        """Resize video to exact dimensions using FFmpeg (much lower memory than MoviePy)."""
        cmd = [
            self.ffmpeg, "-y",
            "-i", str(input_path),
            "-vf", f"scale={width}:{height}:force_divisible_by=2",
            "-c:v", "libx264", "-preset", "fast", "-threads", "2",
            "-x264-params", self._X264_LOW_MEM,
            "-c:a", "aac",
            "-movflags", "+faststart",
            str(output_path),
        ]
        self._run(cmd)
