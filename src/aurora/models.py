"""Pydantic v2 models matching the three AURORA Sprint 1 YAML templates.

These mirror templates/video_brief.yaml, templates/shot_list.yaml and
templates/biomechanical_motion_plan.yaml.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

OutputType = Literal[
    "hero_ad",
    "ugc",
    "cinematic_ad",
    "product_demo",
    "fashion_film",
    "sports_scene",
    "social_vertical",
    "other",
]
AudioStrategy = Literal["native_ai", "external_track", "silent", "mixed"]
ShotType = Literal[
    "establishing",
    "medium",
    "close_up",
    "extreme_close",
    "wide",
    "over_shoulder",
    "product_insert",
    "action",
    "hero_frame",
]
CameraMovement = Literal["pan", "tilt", "dolly", "truck", "static", "handheld"]
SpeedRamp = Literal[
    "linear",
    "slowmo",
    "speedup",
    "flash_in",
    "flash_out",
    "bullet_time",
    "impact",
    "ramp_up",
]
AnchorCaseType = Literal[
    "simple_start",
    "start_and_end",
    "open_end",
    "multishot_per_shot",
    "continuity_from_previous",
    "dialogue_long",
    "complex_scene",
]


# ---------------------------------------------------------------------------
# video_brief.yaml
# ---------------------------------------------------------------------------
class VideoBrief(BaseModel):
    brief_id: Optional[str] = None
    created_at: Optional[str] = None
    operator_intent: str
    output_type: OutputType
    duration_seconds: int = Field(gt=0)
    emotional_beat: str
    product_or_brand: str
    core_action: str
    target_audience: str
    final_frame_description: str
    audio_strategy: AudioStrategy
    success_criteria: list[str] = Field(min_length=1)


# ---------------------------------------------------------------------------
# shot_list.yaml
# ---------------------------------------------------------------------------
class AnchorStrategy(BaseModel):
    case_type: AnchorCaseType
    ff_image_ref: Optional[str] = None
    lf_image_ref: Optional[str] = None
    character_sheet_ref: Optional[str] = None
    prop_sheet_ref: Optional[str] = None
    location_sheet_ref: Optional[str] = None
    previous_clip_last_seconds_ref: Optional[str] = None
    intermediate_screenshot_ref: Optional[str] = None


class Shot(BaseModel):
    shot_number: int
    duration_seconds: float = Field(gt=0)
    shot_type: ShotType
    function: str
    camera_movement: CameraMovement
    speed_ramp: SpeedRamp = "linear"
    biomechanical_motion_plan_id: Optional[str] = None
    anchor_strategy: AnchorStrategy
    prompt_creative: str
    prompt_technical_per_model: dict[str, str] = Field(default_factory=dict)
    prompt_biomechanical: str
    prompt_continuity: str = ""
    negative_constraints: list[str] = Field(min_length=1)


class ShotList(BaseModel):
    project_id: str
    total_duration_seconds: float = 0
    shots: list[Shot] = Field(min_length=1)


# ---------------------------------------------------------------------------
# biomechanical_motion_plan.yaml
# ---------------------------------------------------------------------------
class InitialPose(BaseModel):
    body_position: str
    support_points: list[str] = Field(min_length=1)
    weight_distribution: str


class Torso(BaseModel):
    rotation_degrees: float = 0
    lean_direction: str = ""
    tension_level: Literal["relaxed", "neutral", "tense", "max"] = "neutral"


class Head(BaseModel):
    direction: str = ""
    gaze_target: str = ""
    timing: str = ""


class ArmsHands(BaseModel):
    function: str = ""
    position: str = ""
    motion: str = ""


class Legs(BaseModel):
    angles: str = ""
    support: str = ""
    extension_flexion: str = ""


class ObjectInMotion(BaseModel):
    trajectory_type: Literal["linear", "arc", "parabolic", "irregular"]
    speed_kph: float = 0.0
    contact_points: list[str] = Field(default_factory=list)
    arrival_height_from_ground_cm: float = 0


class PhysicalRestrictions(BaseModel):
    forbidden_movements: list[str] = Field(default_factory=list)
    required_continuity: list[str] = Field(default_factory=list)


class BiomechanicalMotionPlan(BaseModel):
    shot_id: Optional[str] = None
    character_id: Optional[str] = None
    duration_seconds: float = Field(gt=0)
    initial_pose: InitialPose
    torso: Torso = Field(default_factory=Torso)
    head: Head = Field(default_factory=Head)
    arms_hands: ArmsHands = Field(default_factory=ArmsHands)
    legs: Legs = Field(default_factory=Legs)
    center_of_mass_trajectory: str = ""
    object_in_motion: Optional[ObjectInMotion] = None
    physical_restrictions: PhysicalRestrictions = Field(
        default_factory=PhysicalRestrictions
    )


def to_jsonable(model: BaseModel) -> dict[str, Any]:
    """Convenience: dump a pydantic model to a plain JSON-serializable dict."""
    return model.model_dump(mode="json")


# ===========================================================================
# v2.1 FINAL models
# ===========================================================================
ProjectMode = Literal["image", "video_simple", "video_multishot"]
ProjectScope = Literal["image", "video_simple", "video_multishot"]
RouteType = Literal[
    "mcp_callable", "ui_only", "hybrid", "not_verified", "outside_aurora"
]
VerificationSource = Literal[
    "live_mcp", "ui_observed", "operator_reported", "manual_operator",
    "public_docs", "inferred",
]


# ---------------------------------------------------------------------------
# domain_session_lock.yaml (Sección 4 / 12.5)
# ---------------------------------------------------------------------------
class DomainSessionLock(BaseModel):
    domain: str = Field(min_length=1)
    sub_domain: str = Field(min_length=1)
    project_scope: ProjectScope
    allowed_content_boundary: str = "legal, ethical, model-acceptable"
    visual_benchmarks: list[str] = Field(default_factory=list)
    physical_rules: list[str] = Field(default_factory=list)
    style_vocabulary: list[str] = Field(default_factory=list)
    forbidden_cliches: list[str] = Field(default_factory=list)
    common_failure_modes: list[str] = Field(default_factory=list)
    required_success_criteria: list[str] = Field(default_factory=list)
    locked_at: Optional[str] = None


# ---------------------------------------------------------------------------
# benchmark_pack.yaml (Sección 12.1)
# ---------------------------------------------------------------------------
class BenchmarkReference(BaseModel):
    reference_id: str = ""
    url_or_path: str = Field(min_length=1)
    reason: str = ""
    visual_traits: dict[str, Any] = Field(default_factory=dict)


class BenchmarkPack(BaseModel):
    project_id: Optional[str] = None
    acceptance_threshold: int = 85
    references: list[BenchmarkReference] = Field(min_length=1)
    forbidden_traits: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# image_brief.yaml (Sección 12.6)
# ---------------------------------------------------------------------------
ImageType = Literal[
    "genesis", "anchor", "product_hero", "character", "location", "prop",
    "style_frame", "other",
]


class ImageModelRoute(BaseModel):
    route_id: str = ""
    model_id: str = ""
    route_type: RouteType = "not_verified"


class ImageBrief(BaseModel):
    brief_id: Optional[str] = None
    project_id: Optional[str] = None
    operator_intent: str = Field(min_length=1)
    image_type: ImageType
    output_type: str = "other"
    subject: str = ""
    brand_or_product: str = ""
    format: dict[str, Any] = Field(default_factory=dict)
    visual_style: dict[str, Any] = Field(default_factory=dict)
    reference_strategy: dict[str, Any] = Field(default_factory=dict)
    model_route: ImageModelRoute = Field(default_factory=ImageModelRoute)
    success_criteria: list[str] = Field(default_factory=list)
    negative_constraints: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Route verification (Sección 7.4)
# ---------------------------------------------------------------------------
class RouteRegistration(BaseModel):
    route_id: str = ""
    feature_name: str = Field(min_length=1)
    route_type: RouteType
    verification_source: Optional[VerificationSource] = None
    confidence: float = 0.0
    allowed: bool = True
    notes: str = ""


# ---------------------------------------------------------------------------
# Generic gate result
# ---------------------------------------------------------------------------
class GateResult(BaseModel):
    gate: str
    passed: bool
    score: Optional[float] = None
    blocking: bool = True
    reasons: list[str] = Field(default_factory=list)
    notes: str = ""
