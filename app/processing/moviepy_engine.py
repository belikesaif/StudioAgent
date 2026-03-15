import logging
from pathlib import Path
from typing import Optional


def _find_font(bold: bool = False) -> Optional[str]:
    """Locate a usable TrueType font file on the current system."""
    bold_candidates = [
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\calibrib.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\verdanab.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    regular_candidates = [
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\tahoma.ttf",
        r"C:\Windows\Fonts\verdana.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in (bold_candidates if bold else []) + regular_candidates:
        if Path(path).exists():
            return path
    return None


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    """Parse '#RRGGBB' or '#RGB' to (r, g, b)."""
    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def _render_text_image(
    text: str,
    font_size: int,
    color: str,
    position: str,
    video_w: int,
    video_h: int,
) -> "np.ndarray":
    """
    Render a styled text overlay as an RGBA numpy array with:
      - Semi-transparent gradient background strip
      - Drop shadow
      - White text in bold
    Returns shape (video_h, video_w, 4).
    """
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    font_path = _find_font(bold=True) or _find_font(bold=False)

    try:
        font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    # Measure text
    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    pad_x, pad_y = int(font_size * 0.6), int(font_size * 0.4)
    strip_h = text_h + pad_y * 2

    # Determine vertical position
    if position in ("bottom", "bottom_center", "lower_third"):
        strip_top = video_h - strip_h - int(video_h * 0.06)
    elif position in ("top", "top_center"):
        strip_top = int(video_h * 0.04)
    else:  # center
        strip_top = (video_h - strip_h) // 2

    # Canvas
    canvas = Image.new("RGBA", (video_w, video_h), (0, 0, 0, 0))

    # Draw gradient background strip (dark, left-to-right fade-in/out)
    strip = Image.new("RGBA", (video_w, strip_h), (0, 0, 0, 0))
    strip_draw = ImageDraw.Draw(strip)
    for x in range(video_w):
        # Gaussian-ish opacity: peaks at center, fades to edges
        norm = x / video_w
        edge_fade = min(norm, 1 - norm) * 6  # 0→1 over first/last ~17%
        alpha = int(min(1.0, edge_fade) * 185)
        strip_draw.line([(x, 0), (x, strip_h - 1)], fill=(0, 0, 0, alpha))
    canvas.paste(strip, (0, strip_top), strip)

    # Shadow text
    draw = ImageDraw.Draw(canvas)
    text_x = (video_w - text_w) // 2
    text_y = strip_top + pad_y
    shadow_offset = max(2, font_size // 18)
    draw.text(
        (text_x + shadow_offset, text_y + shadow_offset),
        text, font=font, fill=(0, 0, 0, 180),
    )

    # Main text
    try:
        r, g, b = _hex_to_rgb(color)
    except Exception:
        r, g, b = 255, 255, 255
    draw.text((text_x, text_y), text, font=font, fill=(r, g, b, 255))

    return np.array(canvas)


import numpy as np
from PIL import Image
from moviepy import (
    VideoFileClip,
    ImageClip,
    CompositeVideoClip,
    AudioFileClip,
    concatenate_videoclips,
    vfx,
)

from app.agent.models import (
    Scene,
    ActionType,
    OutputFormat,
    TransitionType,
)

logger = logging.getLogger(__name__)


class MoviePyEngine:
    def __init__(self, work_dir: Path):
        self.work_dir = work_dir

    def concatenate_with_transitions(
        self, segment_paths: list[Path], scenes: list[Scene]
    ) -> VideoFileClip:
        """Load segments, apply transitions between them, concatenate."""
        clips = []
        for i, seg_path in enumerate(segment_paths):
            clip = VideoFileClip(str(seg_path))

            # Apply crossfade from previous scene's transition_out
            if i > 0 and i - 1 < len(scenes) and scenes[i - 1].transition_out:
                t = scenes[i - 1].transition_out
                if t.type == TransitionType.CROSSFADE:
                    clip = clip.with_effects([vfx.CrossFadeIn(t.duration)])

            clips.append(clip)

        if not clips:
            raise ValueError("No clips to concatenate")

        result = concatenate_videoclips(clips, method="compose")

        return result

    def apply_zoom_effects(self, clip: VideoFileClip, scenes: list[Scene]) -> VideoFileClip:
        """Apply Ken Burns zoom effects at specified times."""
        zoom_actions = []
        for scene in scenes:
            for action in scene.actions:
                if action.action_type in (ActionType.ZOOM_IN, ActionType.ZOOM_OUT):
                    zoom_actions.append(action)

        if not zoom_actions:
            return clip

        def zoom_frame_transform(get_frame, t):
            frame = get_frame(t)
            for za in zoom_actions:
                if za.start_time <= t <= za.end_time and za.zoom_params:
                    zp = za.zoom_params
                    progress = (t - za.start_time) / max(za.end_time - za.start_time, 0.01)
                    if za.action_type == ActionType.ZOOM_OUT:
                        progress = 1 - progress
                    current_zoom = 1.0 + (zp.zoom_factor - 1.0) * progress

                    h, w = frame.shape[:2]
                    new_w = int(w / current_zoom)
                    new_h = int(h / current_zoom)
                    cx = int(zp.target_x * w)
                    cy = int(zp.target_y * h)
                    x1 = max(0, cx - new_w // 2)
                    y1 = max(0, cy - new_h // 2)
                    x2 = min(w, x1 + new_w)
                    y2 = min(h, y1 + new_h)

                    cropped = frame[y1:y2, x1:x2]
                    frame = np.array(Image.fromarray(cropped).resize((w, h), Image.LANCZOS))
                    break
            return frame

        return clip.transform(zoom_frame_transform)

    def apply_overlays(self, clip: VideoFileClip, scenes: list[Scene]) -> CompositeVideoClip:
        """Apply typography and lower-third overlays using PIL-rendered ImageClips."""
        overlay_clips = [clip]
        video_w, video_h = clip.size

        for scene in scenes:
            for action in scene.actions:
                tp = action.typography_params
                if not tp:
                    continue

                if action.action_type == ActionType.TYPOGRAPHY:
                    try:
                        frame = _render_text_image(
                            text=tp.text,
                            font_size=tp.font_size,
                            color=tp.color or "#FFFFFF",
                            position=tp.position or "bottom_center",
                            video_w=video_w,
                            video_h=video_h,
                        )
                        duration = action.end_time - action.start_time
                        txt_clip = (
                            ImageClip(frame, is_mask=False)
                            .with_start(action.start_time)
                            .with_duration(duration)
                        )
                        # Fade in + out
                        fade = min(0.4, duration * 0.2)
                        txt_clip = txt_clip.with_effects([
                            vfx.CrossFadeIn(fade),
                            vfx.CrossFadeOut(fade),
                        ])
                        overlay_clips.append(txt_clip)
                    except Exception as e:
                        logger.warning(f"Failed to create typography overlay: {e}")

                elif action.action_type == ActionType.LOWER_THIRD:
                    try:
                        frame = _render_text_image(
                            text=tp.text,
                            font_size=36,
                            color="#FFFFFF",
                            position="lower_third",
                            video_w=video_w,
                            video_h=video_h,
                        )
                        duration = action.end_time - action.start_time
                        txt_clip = (
                            ImageClip(frame, is_mask=False)
                            .with_start(action.start_time)
                            .with_duration(duration)
                            .with_effects([
                                vfx.CrossFadeIn(0.3),
                                vfx.CrossFadeOut(0.3),
                            ])
                        )
                        overlay_clips.append(txt_clip)
                    except Exception as e:
                        logger.warning(f"Failed to create lower third overlay: {e}")

        return CompositeVideoClip(overlay_clips)

    def render_final(
        self,
        video_clip,
        output_path: Path,
        target_format: OutputFormat,
        music_path: Optional[Path] = None,
    ):
        """
        Write the final composed video to disk.
        Uses the clip's own (already-processed, in-sync) audio track.
        If music_path is provided, it will be mixed in post via FFmpeg.
        """
        target_w, target_h = target_format.resolution
        final = video_clip.resized((target_w, target_h))

        logger.info(f"Rendering final video to {output_path}")
        final.write_videofile(
            str(output_path),
            codec="libx264",
            audio_codec="aac",
            fps=30,
            preset="fast",
            threads=2,
            ffmpeg_params=["-x264-params", "rc-lookahead=10:ref=1"],
        )
        video_clip.close()
