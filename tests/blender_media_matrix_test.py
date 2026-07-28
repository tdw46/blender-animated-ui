"""Convert representative video, APNG, and selected image-sequence inputs."""

from __future__ import annotations

import json
import os

import addon_utils
import bpy

MODULE = "bl_ext.user_default.blender_animated_ui"
matrix = json.loads(os.environ.get("ANIMTHUMB_MEDIA_MATRIX", "{}"))
required = {"video", "apng", "sequence"}
if set(matrix) != required:
    raise RuntimeError(
        f"Expected media matrix keys {sorted(required)}, got {sorted(matrix)}"
    )

addon_utils.enable(MODULE, default_set=True)
package = __import__(
    MODULE,
    fromlist=["ffmpeg_bridge", "library", "media_ingest"],
)
ffmpeg_status = package.ffmpeg_bridge.status()
executable = str(ffmpeg_status.get("executable", "") or "")
if not executable:
    raise RuntimeError("FFmpeg is unavailable")

results = {}
result_ids = []
for media_type in ("video", "apng", "sequence"):
    sources = matrix[media_type]
    if isinstance(sources, str):
        sources = [sources]
    result = package.media_ingest.ingest_media(
        executable,
        sources,
        display_name=f"Matrix {media_type}",
        target_fps=60,
    )
    if int(result["frame_count"]) < 1:
        raise RuntimeError(f"{media_type} produced no cached frames")
    result_ids.append(str(result["item_id"]))
    source_fps = float(result["source_fps"])
    effective_fps = float(result["effective_fps"])
    if media_type != "sequence":
        if source_fps <= 0.0:
            raise RuntimeError(f"{media_type} source FPS was not detected")
        if effective_fps > source_fps * 1.15:
            raise RuntimeError(f"{media_type} was upsampled beyond its source FPS")
    results[media_type] = {
        "frame_count": int(result["frame_count"]),
        "duration_ms": int(result["duration_ms"]),
        "target_fps": int(result["target_fps"]),
        "source_fps": source_fps,
        "sample_fps": float(result["sample_fps"]),
        "effective_fps": effective_fps,
    }

library_count = package.library.refresh_scene(bpy.context.scene)
loaded_ids = {str(item.item_id) for item in bpy.context.scene.animthumb_items}
missing_ids = sorted(set(result_ids) - loaded_ids)
if missing_ids:
    raise RuntimeError(f"Generated caches were not discovered: {missing_ids}")
print(
    "ANIMTHUMB_MEDIA_MATRIX",
    {
        "formats": results,
        "library_count": library_count,
    },
)
for item_id in result_ids:
    if not package.library.remove_item(item_id):
        raise RuntimeError(f"Media matrix cache cleanup failed: {item_id}")
addon_utils.disable(MODULE)
