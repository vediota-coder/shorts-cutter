"""Smart reframe: умное центрирование 9:16 с учётом сцены, активного спикера и экрана."""
from .pipeline import SmartAnalysis, analyze_video, build_scenes, apply_corrections, render_smart
from .types import (
    BBox,
    FaceDetection,
    FaceTrack,
    ScreenRegion,
    ScreenType,
    LayoutType,
    SceneSegment,
    FrameProbe,
    VideoMeta,
    FrameCorrection,
)

__all__ = [
    "BBox", "FaceDetection", "FaceTrack",
    "ScreenRegion", "ScreenType",
    "LayoutType", "SceneSegment", "FrameProbe", "VideoMeta",
    "FrameCorrection",
    "SmartAnalysis", "analyze_video", "build_scenes", "apply_corrections", "render_smart",
]
