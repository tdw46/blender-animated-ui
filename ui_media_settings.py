"""Shared file-picker and per-item refresh settings presentation."""

from __future__ import annotations

from pathlib import Path

from .constants import CACHE_FRAME_WARNING_THRESHOLD
from .media_settings import (
    MediaAnalysis,
    MediaImportSettings,
    estimate_cache,
)


def import_settings_from_operator(operator) -> MediaImportSettings:
    return MediaImportSettings(
        target_fps=int(operator.target_fps),
        sequence_order=str(operator.sequence_order),
        trim_media=bool(operator.trim_media),
        trim_start_frame=int(operator.trim_start_frame),
        trim_end_frame=int(operator.trim_end_frame),
    ).normalized()


def analysis_from_operator(operator, paths: tuple[Path, ...]) -> MediaAnalysis:
    return MediaAnalysis(
        is_sequence=len(paths) > 1
        or bool(getattr(operator, "analysis_is_sequence", False)),
        selection_count=max(
            len(paths),
            int(getattr(operator, "analysis_selection_count", 0) or 0),
        ),
        source_fps=max(
            0.0,
            float(getattr(operator, "analysis_source_fps", 0.0) or 0.0),
        ),
        duration_seconds=max(
            0.0,
            float(getattr(operator, "analysis_duration_seconds", 0.0) or 0.0),
        ),
        total_frames=max(
            0,
            int(getattr(operator, "analysis_total_frames", 0) or 0),
        ),
        message=str(getattr(operator, "analysis_message", "") or ""),
    )


def _draw_trim_settings(settings_box, operator, full_frame_count: int) -> None:
    settings_box.separator(factor=0.5)
    settings_box.prop(operator, "trim_media", text="Trim Media")
    trim_column = settings_box.column(align=True)
    trim_column.enabled = bool(operator.trim_media)
    trim_column.prop(operator, "trim_start_frame", text="Begin Frame")
    end_label = "End Frame"
    if int(operator.trim_end_frame) <= 0 and full_frame_count <= 0:
        end_label = "End Frame (0 = Media End)"
    trim_column.prop(operator, "trim_end_frame", text=end_label)
    if not operator.trim_media:
        settings_box.label(
            text="Full source range will be cached",
            icon="CHECKMARK",
        )


def _draw_cache_size_warning(settings_box, estimated_frames: int) -> None:
    if estimated_frames <= CACHE_FRAME_WARNING_THRESHOLD:
        return
    warning = settings_box.row()
    warning.alert = True
    warning.label(
        text=(
            f"Large cache: about {estimated_frames:,} frames. "
            "Lower FPS or enable Trim Media if desired."
        ),
        icon="ERROR",
    )


def draw_media_settings(layout, context, operator, paths: tuple[Path, ...]) -> None:
    """Draw one canonical settings view for ingest and per-item refresh."""
    settings = import_settings_from_operator(operator)
    analysis = analysis_from_operator(operator, paths)
    estimate = estimate_cache(analysis, settings)
    settings_box = layout.box()
    settings_box.prop(operator, "display_name", text="Imported Name")
    settings_box.separator(factor=0.5)

    if analysis.is_sequence:
        settings_box.label(
            text=f"Image Sequence · {analysis.selection_count} selected",
            icon="SEQ_STRIP_META",
        )
        settings_box.prop(operator, "target_fps", text="Playback FPS", slider=True)
        settings_box.prop(operator, "sequence_order", text="Frame Order")
        full_frame_count = max(analysis.selection_count, analysis.total_frames)
        _draw_trim_settings(settings_box, operator, full_frame_count)
        settings_box.label(
            text=(
                f"Expected cache: {estimate.cached_frames} frames · "
                f"{estimate.preview_duration_seconds:.2f} seconds"
            ),
            icon="INFO",
        )
    else:
        settings_box.label(text="Selected Media Analysis", icon="FILE_MOVIE")
        if paths:
            settings_box.label(text=paths[0].name, icon="FILE")
        if analysis.source_fps > 0.0:
            settings_box.label(text=f"Native frame rate: {analysis.source_fps:.3f} FPS")
        else:
            settings_box.label(
                text=analysis.message or "Select media to analyze",
                icon="INFO",
            )
        if analysis.duration_seconds > 0.0:
            settings_box.label(
                text=f"Source duration: {analysis.duration_seconds:.2f} seconds"
            )
        settings_box.prop(
            operator,
            "target_fps",
            text="Import FPS Ceiling",
            slider=True,
        )
        _draw_trim_settings(settings_box, operator, analysis.total_frames)
        settings_box.label(
            text=f"Expected import rate: {estimate.sample_fps:.3f} FPS",
            icon="TIME",
        )
        if estimate.preview_duration_seconds > 0.0:
            settings_box.label(
                text=(
                    f"Expected cache: {estimate.cached_frames} frames · "
                    f"{estimate.preview_duration_seconds:.2f} seconds"
                ),
                icon="INFO",
            )

    _draw_cache_size_warning(settings_box, estimate.cached_frames)
    live_limit = int(getattr(context.window_manager, "animthumb_preview_fps", 10) or 10)
    settings_box.separator(factor=0.5)
    settings_box.label(
        text=f"Current gallery playback ceiling: {live_limit} FPS",
        icon="PLAY",
    )
