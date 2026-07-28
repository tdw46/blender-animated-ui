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
for media_type in ("video", "apng", "sequence"):
    sources = matrix[media_type]
    if isinstance(sources, str):
        sources = [sources]
    result = package.media_ingest.ingest_media(
        executable,
        sources,
        display_name=f"Matrix {media_type}",
    )
    if int(result["frame_count"]) < 1:
        raise RuntimeError(f"{media_type} produced no cached frames")
    results[media_type] = {
        "frame_count": int(result["frame_count"]),
        "duration_ms": int(result["duration_ms"]),
    }

library_count = package.library.refresh_scene(bpy.context.scene)
if library_count != 3:
    raise RuntimeError(f"Expected three caches, found {library_count}")
print(
    "ANIMTHUMB_MEDIA_MATRIX",
    {
        "formats": results,
        "library_count": library_count,
    },
)
addon_utils.disable(MODULE)
