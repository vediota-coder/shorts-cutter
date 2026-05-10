from .lip_motion import compute_lip_motion
from .lip_motion import active_speaker_per_frame as active_speaker_per_frame_lip

# LR-ASD (ML модель, IJCV 2025) — приоритетная если доступна
from . import lr_asd

__all__ = [
    "compute_lip_motion",
    "active_speaker_per_frame_lip",
    "lr_asd",
]


def active_speaker_per_frame(*args, **kwargs):
    """Совместимость со старым API — использует lip-motion."""
    return active_speaker_per_frame_lip(*args, **kwargs)

