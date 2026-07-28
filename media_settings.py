"""Pure import-analysis models shared by Blender and non-Blender integrations."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .constants import MAX_PREVIEW_FPS
from .frame_rate import clamp_preview_fps, target_sample_fps
from .media_selection import DEFAULT_SEQUENCE_ORDER


@dataclass(frozen=True, slots=True)
class MediaImportSettings:
    """User-controlled settings for one media-to-cache conversion."""

    target_fps: int = MAX_PREVIEW_FPS
    sequence_order: str = DEFAULT_SEQUENCE_ORDER
    trim_media: bool = False
    trim_start_frame: int = 1
    trim_end_frame: int = 0

    def normalized(self) -> MediaImportSettings:
        return MediaImportSettings(
            target_fps=clamp_preview_fps(self.target_fps),
            sequence_order=str(self.sequence_order or DEFAULT_SEQUENCE_ORDER),
            trim_media=bool(self.trim_media),
            trim_start_frame=max(1, int(self.trim_start_frame)),
            trim_end_frame=max(0, int(self.trim_end_frame)),
        )


@dataclass(frozen=True, slots=True)
class MediaAnalysis:
    """Probe information used by both the file picker and refresh dialog."""

    is_sequence: bool = False
    selection_count: int = 0
    source_fps: float = 0.0
    duration_seconds: float = 0.0
    total_frames: int = 0
    message: str = ""


@dataclass(frozen=True, slots=True)
class CacheEstimate:
    """Estimated cache characteristics shown before conversion."""

    sample_fps: float
    selected_source_frames: int
    selected_duration_seconds: float
    cached_frames: int
    preview_duration_seconds: float


def selected_frame_count(
    total_frames: int,
    settings: MediaImportSettings,
) -> int:
    """Return the inclusive selected range without changing the source window."""
    count = max(0, int(total_frames))
    resolved = settings.normalized()
    if count <= 0 or not resolved.trim_media:
        return count
    start_frame = min(count, resolved.trim_start_frame)
    end_frame = (
        count if resolved.trim_end_frame <= 0 else min(count, resolved.trim_end_frame)
    )
    return max(0, end_frame - start_frame + 1)


def estimate_cache(
    analysis: MediaAnalysis,
    settings: MediaImportSettings,
) -> CacheEstimate:
    """Estimate cache size using the same frame-rate contract as ingestion."""
    resolved = settings.normalized()
    full_frame_count = max(
        int(analysis.selection_count) if analysis.is_sequence else 0,
        int(analysis.total_frames),
    )
    selected_frames = selected_frame_count(full_frame_count, resolved)

    if analysis.is_sequence:
        duration = (
            selected_frames / float(resolved.target_fps) if selected_frames > 0 else 0.0
        )
        return CacheEstimate(
            sample_fps=float(resolved.target_fps),
            selected_source_frames=selected_frames,
            selected_duration_seconds=duration,
            cached_frames=selected_frames,
            preview_duration_seconds=duration,
        )

    sample_fps = target_sample_fps(
        max(0.0, float(analysis.duration_seconds)),
        resolved.target_fps,
        1,
        source_fps=max(0.0, float(analysis.source_fps)),
    )
    selected_duration = max(0.0, float(analysis.duration_seconds))
    if resolved.trim_media and analysis.source_fps > 0.0 and selected_frames > 0:
        selected_duration = selected_frames / float(analysis.source_fps)
    cached_frames = (
        max(1, int(math.ceil(selected_duration * sample_fps)))
        if selected_duration > 0.0
        else 1
    )
    preview_duration = (
        cached_frames / sample_fps if cached_frames > 1 and sample_fps > 0.0 else 0.0
    )
    return CacheEstimate(
        sample_fps=sample_fps,
        selected_source_frames=selected_frames,
        selected_duration_seconds=selected_duration,
        cached_frames=cached_frames,
        preview_duration_seconds=preview_duration,
    )
