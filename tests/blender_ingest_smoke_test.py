"""Exercise the public ingest operator and preview cache inside Blender."""

from __future__ import annotations

import os

import addon_utils
import bpy

MODULE = "bl_ext.user_default.blender_animated_ui"
sample_path = os.environ.get("ANIMTHUMB_SAMPLE_MEDIA", "")
if not sample_path:
    raise RuntimeError("ANIMTHUMB_SAMPLE_MEDIA is required")

addon_utils.enable(MODULE, default_set=True)
bpy.context.window_manager.animthumb_preview_fps = 60
result = set(bpy.ops.animthumb.ingest_media(filepath=sample_path))
if "FINISHED" not in result:
    raise RuntimeError(f"Ingest operator returned {sorted(result)}")

scene = bpy.context.scene
if len(scene.animthumb_items) != 1:
    raise RuntimeError(f"Expected one gallery item, found {len(scene.animthumb_items)}")
item = scene.animthumb_items[0]
if item.frame_count <= 1:
    raise RuntimeError(f"Expected an animated cache, found {item.frame_count} frame(s)")

package = __import__(
    MODULE,
    fromlist=["cache_format", "library", "preview_cache", "preview_engine"],
)
preview_cache = package.preview_cache
preview_engine = package.preview_engine
metadata = package.cache_format.read_metadata(item.cache_dir)
if float(metadata.get("target_fps", 0.0)) != 60.0:
    raise RuntimeError("Ingest did not honor the configured preview frame rate")
source_fps = float(metadata.get("source_fps", 0.0))
effective_fps = float(metadata.get("effective_fps", 0.0))
if source_fps <= 0.0:
    raise RuntimeError("Ingest did not record the source frame rate")
if effective_fps > source_fps * 1.15:
    raise RuntimeError("Ingest upsampled beyond the source frame rate")
cached = preview_cache.load_item(item)
if cached is None:
    raise RuntimeError("Preview cache did not load")
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
        "target_fps": float(metadata["target_fps"]),
        "source_fps": source_fps,
        "sample_fps": float(metadata["sample_fps"]),
        "effective_fps": effective_fps,
        "icon_id": int(icon_id),
        "signature": signature,
        "next_interval_seconds": float(interval),
    },
)

if not package.library.remove_item(item.item_id):
    raise RuntimeError("Ingest smoke cache cleanup failed")
addon_utils.disable(MODULE)
