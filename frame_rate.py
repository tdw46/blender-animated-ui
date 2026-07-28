"""Pure frame-rate helpers shared by ingest and live preview playback."""

from __future__ import annotations

import math

from .constants import (
    DEFAULT_PREVIEW_FPS,
    MAX_PREVIEW_FPS,
    MIN_PREVIEW_FPS,
)


def clamp_preview_fps(value: int | float | None) -> int:
    """Return a supported integer preview rate."""
    try:
        resolved = int(round(float(value)))
    except (TypeError, ValueError):
        resolved = DEFAULT_PREVIEW_FPS
    return max(MIN_PREVIEW_FPS, min(resolved, MAX_PREVIEW_FPS))


def frame_interval_ms(value: int | float | None) -> int:
    """Return a whole-millisecond interval that never exceeds the rate."""
    return max(1, int(math.ceil(1000.0 / clamp_preview_fps(value))))


def sampled_clock_ms(now_ms: int, fps_limit: int | float | None) -> int:
    """Quantize a clock to a maximum visible sampling rate.

    ``None`` preserves the source clock for integrations that do not want a
    live playback cap.
    """
    resolved_now = max(0, int(now_ms))
    if fps_limit is None:
        return resolved_now
    interval_ms = frame_interval_ms(fps_limit)
    return (resolved_now // interval_ms) * interval_ms


def target_sample_fps(
    duration_seconds: float,
    requested_fps: int | float | None,
    max_frames: int,
) -> float:
    """Bound FFmpeg sampling by both the requested rate and frame budget."""
    requested = float(clamp_preview_fps(requested_fps))
    duration = max(0.0, float(duration_seconds))
    frame_budget = max(1, int(max_frames))
    if duration <= 0.0:
        return requested
    return max(0.01, min(requested, frame_budget / duration))


def sample_wait_ms(
    now_ms: int,
    sampled_now_ms: int,
    source_boundary_wait_ms: int,
    fps_limit: int | float | None,
) -> int:
    """Return the next source boundary, aligned to the playback FPS grid."""
    source_wait = max(1, int(source_boundary_wait_ms))
    if fps_limit is None:
        return source_wait
    interval_ms = frame_interval_ms(fps_limit)
    ticks = max(1, int(math.ceil(source_wait / interval_ms)))
    target_ms = max(0, int(sampled_now_ms)) + (ticks * interval_ms)
    return max(1, target_ms - max(0, int(now_ms)))


def effective_fps(frame_count: int, duration_ms: int) -> float:
    """Calculate the rate represented by a finished uniform cache."""
    frames = max(0, int(frame_count))
    duration = max(0, int(duration_ms))
    if frames <= 1 or duration <= 0:
        return 0.0
    return (frames * 1000.0) / duration
