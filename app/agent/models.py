from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional


# --- Enums ---

class ActionType(str, Enum):
    CUT = "cut"
    KEEP = "keep"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    SLOW_MOTION = "slow_motion"
    SPEED_UP = "speed_up"
    TYPOGRAPHY = "typography"
    ANIMATED_CAPTION = "animated_caption"
    COLOR_GRADE = "color_grade"
    TRANSITION = "transition"
    MOTION_GRAPHIC = "motion_graphic"
    LOWER_THIRD = "lower_third"


class TransitionType(str, Enum):
    CUT = "cut"
    CROSSFADE = "crossfade"
    FADE_TO_BLACK = "fade_to_black"
    WIPE = "wipe"
    ZOOM_TRANSITION = "zoom_transition"


class ColorGradePreset(str, Enum):
    WARM = "warm"
    COOL = "cool"
    CINEMATIC = "cinematic"
    VIBRANT = "vibrant"
    DESATURATED = "desaturated"
    HIGH_CONTRAST = "high_contrast"


# --- Component Models ---

class ZoomParams(BaseModel):
    target_x: float = Field(0.5, description="Normalized X center of zoom (0-1)")
    target_y: float = Field(0.5, description="Normalized Y center of zoom (0-1)")
    zoom_factor: float = Field(1.3, description="How much to zoom (1.0 = no zoom)")
    duration: float = Field(2.0, description="Duration of the zoom effect in seconds")


class SpeedParams(BaseModel):
    factor: float = Field(description="Speed multiplier (0.5 = half speed, 2.0 = double)")


class TypographyParams(BaseModel):
    text: str
    font_size: int = 48
    color: str = "#FFFFFF"
    background_color: Optional[str] = None
    position: str = "center"  # center, top, bottom, lower_third
    animation: str = "fade_in"  # fade_in, typewriter, pop, slide_up
    duration: float = 3.0


class TransitionParams(BaseModel):
    type: TransitionType = TransitionType.CROSSFADE
    duration: float = 0.5


class ColorGradeParams(BaseModel):
    preset: ColorGradePreset = ColorGradePreset.CINEMATIC
    brightness: float = Field(0.0, description="FFmpeg eq brightness: 0.0 = neutral, -0.1 = darker, +0.1 = brighter. Range: -0.5 to +0.5")
    contrast: float = Field(1.0, description="FFmpeg eq contrast: 1.0 = neutral, 1.2 = more contrast, 0.8 = less contrast. Range: 0.5 to 2.0")
    saturation: float = Field(1.0, description="FFmpeg eq saturation: 1.0 = neutral, 1.3 = more vivid, 0.7 = muted. Range: 0.0 to 3.0")
    temperature: float = Field(0.0, description="Color temperature shift: 0.0 = neutral, +0.1 = warmer, -0.1 = cooler. Range: -0.5 to +0.5")


class MotionGraphicParams(BaseModel):
    type: str = "emphasis_circle"
    target_x: float = 0.5
    target_y: float = 0.5
    color: str = "#FFD700"
    duration: float = 2.0


# --- Edit Action ---

class EditAction(BaseModel):
    action_type: ActionType
    start_time: float = Field(description="Start time in seconds (relative to source video)")
    end_time: float = Field(description="End time in seconds (relative to source video)")
    zoom_params: Optional[ZoomParams] = None
    speed_params: Optional[SpeedParams] = None
    typography_params: Optional[TypographyParams] = None
    transition_params: Optional[TransitionParams] = None
    color_grade_params: Optional[ColorGradeParams] = None
    motion_graphic_params: Optional[MotionGraphicParams] = None


# --- Subtitle ---

class Subtitle(BaseModel):
    start_time: float
    end_time: float
    text: str
    speaker: str = "Speaker"


# --- Scene ---

class Scene(BaseModel):
    scene_id: int
    start_time: float = Field(description="Start time in source video (seconds)")
    end_time: float = Field(description="End time in source video (seconds)")
    description: str = Field(description="Brief description of scene content")
    energy_level: str = Field(description="low, medium, or high")
    actions: list[EditAction] = Field(default_factory=list)
    transition_out: Optional[TransitionParams] = None


# --- Music ---

class VolumeKeyframe(BaseModel):
    time: float
    volume: float


class MusicDirective(BaseModel):
    suggested_genre: str
    suggested_mood: str
    bpm_range: str = "90-120"
    volume_keyframes: list[VolumeKeyframe] = Field(default_factory=list)


# --- Output Format ---

class CropRegion(BaseModel):
    x: float = Field(description="Normalized left edge (0-1)")
    y: float = Field(description="Normalized top edge (0-1)")
    width: float = Field(description="Normalized width (0-1)")
    height: float = Field(description="Normalized height (0-1)")


class OutputFormat(BaseModel):
    aspect_ratio: str
    resolution: list[int]
    crop_region: Optional[CropRegion] = None


# --- Top-Level Editing Plan ---

class VideoMetadata(BaseModel):
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool


class EditingPlan(BaseModel):
    video_metadata: VideoMetadata
    scenes: list[Scene]
    subtitles: list[Subtitle]
    music: MusicDirective
    color_grade_global: Optional[ColorGradeParams] = None
    output_formats: list[OutputFormat]
    summary: str = Field(description="Brief summary of editing strategy")
