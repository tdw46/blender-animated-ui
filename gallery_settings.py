"""Pure defaults and thumbnail-scale normalization for gallery settings."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .constants import DEFAULT_PREVIEW_FPS
from .gallery_query import (
    DEFAULT_GALLERY_MEDIA_TYPE,
    DEFAULT_GALLERY_SEARCH,
    DEFAULT_GALLERY_SORT,
)

DEFAULT_OPTIMIZED_PLAYBACK = False

THUMBNAIL_SCALE_VISUAL_MULTIPLIER = 1.5
DEFAULT_THUMBNAIL_SCALE = 1.0
MIN_THUMBNAIL_SCALE = 0.5
MAX_THUMBNAIL_SCALE = 4.0


@dataclass(frozen=True, slots=True)
class GallerySettings:
    """Reusable default state for the settings-cog controls."""

    search_text: str = DEFAULT_GALLERY_SEARCH
    media_type: str = DEFAULT_GALLERY_MEDIA_TYPE
    sort_mode: str = DEFAULT_GALLERY_SORT
    thumbnail_scale: float = DEFAULT_THUMBNAIL_SCALE
    preview_fps: int = DEFAULT_PREVIEW_FPS
    optimized_playback: bool = DEFAULT_OPTIMIZED_PLAYBACK


DEFAULT_GALLERY_SETTINGS = GallerySettings()


def normalized_thumbnail_scale(value: object) -> float:
    """Map the public 1.0 baseline onto the original 1.5 visual scale."""
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        numeric_value = DEFAULT_THUMBNAIL_SCALE
    if not math.isfinite(numeric_value):
        numeric_value = DEFAULT_THUMBNAIL_SCALE
    clamped_value = max(
        MIN_THUMBNAIL_SCALE,
        min(numeric_value, MAX_THUMBNAIL_SCALE),
    )
    return clamped_value * THUMBNAIL_SCALE_VISUAL_MULTIPLIER
