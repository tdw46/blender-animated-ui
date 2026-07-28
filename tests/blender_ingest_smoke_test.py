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
result = set(bpy.ops.animthumb.ingest_media(filepath=sample_path))
if "FINISHED" not in result:
    raise RuntimeError(f"Ingest operator returned {sorted(result)}")

scene = bpy.context.scene
if len(scene.animthumb_items) != 1:
    raise RuntimeError(f"Expected one gallery item, found {len(scene.animthumb_items)}")
item = scene.animthumb_items[0]
if item.frame_count <= 1:
    raise RuntimeError(f"Expected an animated cache, found {item.frame_count} frame(s)")

package = __import__(MODULE, fromlist=["preview_cache", "preview_engine"])
preview_cache = package.preview_cache
preview_engine = package.preview_engine
cached = preview_cache.load_item(item)
if cached is None:
    raise RuntimeError("Preview cache did not load")
now_ms = preview_engine.preview_clock_ms()
icon_id = preview_cache.icon_id(item.item_id, now_ms)
signature = preview_cache.frame_signature((item.item_id,), now_ms)
interval = preview_cache.next_interval_seconds((item.item_id,), now_ms)
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
        "icon_id": int(icon_id),
        "signature": signature,
        "next_interval_seconds": float(interval),
    },
)

addon_utils.disable(MODULE)
