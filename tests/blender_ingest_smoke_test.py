"""Exercise the public ingest operator and preview cache inside Blender."""

from __future__ import annotations

import os
from pathlib import Path

import addon_utils
import bpy

MODULE = os.environ.get(
    "ANIMTHUMB_MODULE",
    "bl_ext.user_default.blender_animated_ui",
)
sample_path = os.environ.get("ANIMTHUMB_SAMPLE_MEDIA", "")
if not sample_path:
    raise RuntimeError("ANIMTHUMB_SAMPLE_MEDIA is required")

addon_utils.enable(MODULE, default_set=True)
bpy.context.window_manager.animthumb_preview_fps = 60
result = set(bpy.ops.animthumb.ingest_media(filepath=sample_path))
if "FINISHED" not in result:
    raise RuntimeError(f"Ingest operator returned {sorted(result)}")

scene = bpy.context.scene
resolved_sample_path = Path(sample_path).resolve()
matching_items = tuple(
    item
    for item in scene.animthumb_items
    if Path(str(item.source_path)).resolve() == resolved_sample_path
)
if len(matching_items) != 1:
    raise RuntimeError(
        f"Expected one cache for {resolved_sample_path}, found {len(matching_items)}"
    )
item = matching_items[0]
if item.frame_count <= 1:
    raise RuntimeError(f"Expected an animated cache, found {item.frame_count} frame(s)")

package = __import__(
    MODULE,
    fromlist=["cache_format", "library", "preview_cache", "preview_engine"],
)
preview_cache = package.preview_cache
preview_engine = package.preview_engine
metadata = package.cache_format.read_metadata(item.cache_dir)
if float(metadata.get("target_fps", 0.0)) != 22.0:
    raise RuntimeError("Ingest did not honor the configured preview frame rate")
expected_source_type = resolved_sample_path.suffix[1:].upper()
if str(metadata.get("source_type", "") or "") != expected_source_type:
    raise RuntimeError("Ingest did not record the source media type")
if not str(metadata.get("date_added_utc", "") or ""):
    raise RuntimeError("Ingest did not record its date-added metadata")
source_fps = float(metadata.get("source_fps", 0.0))
effective_fps = float(metadata.get("effective_fps", 0.0))
if source_fps <= 0.0:
    raise RuntimeError("Ingest did not record the source frame rate")
if effective_fps > source_fps * 1.15:
    raise RuntimeError("Ingest upsampled beyond the source frame rate")
if source_fps >= 8.0 and effective_fps < 7.5:
    raise RuntimeError("Ingest dropped supported media below the 8 FPS floor")
source_duration_ms = int(metadata.get("source_duration_ms", 0))
preview_duration_ms = int(metadata.get("preview_duration_ms", 0))
if source_duration_ms <= 0 or preview_duration_ms <= 0:
    raise RuntimeError("Ingest did not record source and preview durations")
duration_tolerance_ms = max(150, int(round(source_duration_ms * 0.05)))
if abs(preview_duration_ms - source_duration_ms) > duration_tolerance_ms:
    raise RuntimeError(
        "Default ingest shortened the preview window: "
        f"source={source_duration_ms}ms preview={preview_duration_ms}ms"
    )
if bool(metadata.get("trim_media", True)):
    raise RuntimeError("Default ingest unexpectedly enabled Trim Media")
cache_image_format = str(metadata.get("cache_image_format", "") or "")
if cache_image_format not in {"JPEG", "WEBP"}:
    raise RuntimeError(f"Unexpected optimized cache format: {cache_image_format}")
extensions = {record.path.suffix.lower() for record in metadata["records"]}
expected_extension = ".jpg" if cache_image_format == "JPEG" else ".webp"
if extensions != {expected_extension}:
    raise RuntimeError(
        f"Cache format {cache_image_format} used unexpected files: {extensions}"
    )
cached = preview_cache.load_item(item)
if cached is None:
    raise RuntimeError("Preview cache did not load")
native_display_fps = preview_cache.display_frame_rate(item.item_id, fps_limit=60)
floor_display_fps = preview_cache.display_frame_rate(item.item_id, fps_limit=8)
if abs(floor_display_fps - min(8.0, native_display_fps)) > 0.15:
    raise RuntimeError("Live preview FPS did not react to the configured ceiling")
high_rate_transitions = 0
floor_rate_transitions = 0
if native_display_fps > 8.5:
    sample_window_ms = min(1000, max(2, int(item.duration_ms)))
    high_indices = tuple(
        preview_cache.frame_index(item.item_id, tick_ms, fps_limit=60)
        for tick_ms in range(sample_window_ms)
    )
    floor_indices = tuple(
        preview_cache.frame_index(item.item_id, tick_ms, fps_limit=8)
        for tick_ms in range(sample_window_ms)
    )
    high_rate_transitions = sum(
        current != previous for previous, current in zip(high_indices, high_indices[1:])
    )
    floor_rate_transitions = sum(
        current != previous
        for previous, current in zip(floor_indices, floor_indices[1:])
    )
    if floor_rate_transitions >= high_rate_transitions:
        raise RuntimeError("Frame selection ignored the lower live FPS ceiling")
now_ms = preview_engine.preview_clock_ms()
icon_id = preview_cache.icon_id(item.item_id, now_ms, fps_limit=60)
signature = preview_cache.frame_signature(
    (item.item_id,),
    now_ms,
    fps_limit=60,
)
interval = preview_cache.next_interval_seconds(
    (item.item_id,),
    now_ms,
    fps_limit=60,
)
if not signature:
    raise RuntimeError("Animated frame signature is empty")
if interval <= 0.0:
    raise RuntimeError("Preview scheduler returned a non-positive interval")

print(
    "ANIMTHUMB_INGEST",
    {
        "operator": sorted(result),
        "frame_count": int(item.frame_count),
        "duration_ms": int(item.duration_ms),
        "source_duration_ms": source_duration_ms,
        "preview_duration_ms": preview_duration_ms,
        "cache_image_format": cache_image_format,
        "full_range_preserved": True,
        "target_fps": float(metadata["target_fps"]),
        "source_fps": source_fps,
        "sample_fps": float(metadata["sample_fps"]),
        "effective_fps": effective_fps,
        "native_display_fps": native_display_fps,
        "floor_display_fps": floor_display_fps,
        "high_rate_transitions": high_rate_transitions,
        "floor_rate_transitions": floor_rate_transitions,
        "icon_id": int(icon_id),
        "signature": signature,
        "next_interval_seconds": float(interval),
    },
)

if not package.library.remove_item(item.item_id):
    raise RuntimeError("Ingest smoke cache cleanup failed")
addon_utils.disable(MODULE)
