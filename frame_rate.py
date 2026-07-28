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
    """Return a whole-millisecond interval for any positive media rate.

    This intentionally does not apply the configurable preview-rate floor.
    Encoded media whose native rate is below that floor must retain its native
    timing instead of being sped up.
    """
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        resolved = float(DEFAULT_PREVIEW_FPS)
    resolved = max(0.01, min(resolved, float(MAX_PREVIEW_FPS)))
    return max(1, int(math.ceil(1000.0 / resolved)))


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
    *,
    source_fps: float = 0.0,
) -> float:
    """Choose the requested/native cache rate.

    ``max_frames`` and ``duration_seconds`` remain part of the public call
    contract for integrations migrating from the earlier bounded-cache demo.
    They no longer lower the sampling rate or shorten the preview window.
    """
    requested = float(clamp_preview_fps(requested_fps))
    del duration_seconds, max_frames
    native = max(0.0, float(source_fps))
    rate = min(requested, native) if native > 0.0 else requested
    return max(0.01, rate)


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


def active_display_fps(
    cache_fps: int | float,
    *,
    source_fps: int | float = 0.0,
    requested_fps: int | float | None = None,
) -> float:
    """Resolve the truthful per-item rate shown by a live preview UI."""
    limits = [
        rate
        for rate in (
            max(0.0, float(cache_fps)),
            max(0.0, float(source_fps)),
            max(0.0, float(requested_fps)) if requested_fps is not None else 0.0,
        )
        if rate > 0.0
    ]
    return min(limits) if limits else 0.0
