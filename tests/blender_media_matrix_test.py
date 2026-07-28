"""Convert representative video, APNG, and selected image-sequence inputs."""

from __future__ import annotations

import json
import os

import addon_utils
import bpy

MODULE = os.environ.get(
    "ANIMTHUMB_MODULE",
    "bl_ext.user_default.blender_animated_ui",
)
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
    if media_type == "sequence" and int(result["frame_count"]) != len(sources):
        raise RuntimeError(
            "Image sequence did not preserve every selected frame: "
            f"{len(sources)} selected, {result['frame_count']} cached"
        )
    source_duration_ms = int(result["source_duration_ms"])
    preview_duration_ms = int(result["duration_ms"])
    duration_tolerance_ms = max(150, int(round(source_duration_ms * 0.05)))
    if (
        source_duration_ms > 0
        and abs(preview_duration_ms - source_duration_ms) > duration_tolerance_ms
    ):
        raise RuntimeError(
            f"{media_type} cache shortened its source window: "
            f"{source_duration_ms}ms -> {preview_duration_ms}ms"
        )
    cache_image_format = str(result.get("cache_image_format", "") or "")
    if cache_image_format not in {"JPEG", "WEBP"}:
        raise RuntimeError(
            f"{media_type} did not use an optimized cache format: {cache_image_format}"
        )
    result_ids.append(str(result["item_id"]))
    source_fps = float(result["source_fps"])
    effective_fps = float(result["effective_fps"])
    if media_type != "sequence":
        if source_fps <= 0.0:
            raise RuntimeError(f"{media_type} source FPS was not detected")
        if effective_fps > source_fps * 1.15:
            raise RuntimeError(f"{media_type} was upsampled beyond its source FPS")
        if source_fps >= 8.0 and effective_fps < 7.5:
            raise RuntimeError(f"{media_type} fell below the 8 FPS floor")
    results[media_type] = {
        "frame_count": int(result["frame_count"]),
        "duration_ms": preview_duration_ms,
        "source_duration_ms": source_duration_ms,
        "cache_image_format": cache_image_format,
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
