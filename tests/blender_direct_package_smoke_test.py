"""Validate source-package registration and optimized caches across Blender versions."""

from __future__ import annotations

import importlib
import os
import sys

import bpy

source_parent = os.environ.get("ANIMTHUMB_SOURCE_PARENT", "")
ffmpeg = os.environ.get("ANIMTHUMB_FFMPEG", "")
opaque_media = os.environ.get("ANIMTHUMB_OPAQUE_MEDIA", "")
alpha_media = os.environ.get("ANIMTHUMB_ALPHA_MEDIA", "")
if not all((source_parent, ffmpeg, opaque_media, alpha_media)):
    raise RuntimeError(
        "ANIMTHUMB_SOURCE_PARENT, ANIMTHUMB_FFMPEG, ANIMTHUMB_OPAQUE_MEDIA, "
        "and ANIMTHUMB_ALPHA_MEDIA are required"
    )

sys.path.insert(0, source_parent)
package = importlib.import_module("blender_animated_ui")
package.register()

result_ids: list[str] = []
try:
    operator_properties = bpy.ops.animthumb.ingest_media.get_rna_type().properties
    if int(operator_properties["target_fps"].default) != 60:
        raise RuntimeError("Source-package import FPS default is not 60")
    if bool(operator_properties["trim_media"].default):
        raise RuntimeError("Source-package Trim Media default is not disabled")

    results = (
        package.media_ingest.ingest_media(
            ffmpeg,
            [opaque_media],
            display_name="Version Matrix Opaque",
            target_fps=60,
        ),
        package.media_ingest.ingest_media(
            ffmpeg,
            [alpha_media],
            display_name="Version Matrix Alpha",
            target_fps=60,
        ),
    )
    expected_formats = ("JPEG", "WEBP")
    for result, expected_format in zip(results, expected_formats):
        result_ids.append(str(result["item_id"]))
        if str(result["cache_image_format"]) != expected_format:
            raise RuntimeError(
                f"Expected {expected_format}, got {result['cache_image_format']}"
            )

    package.library.refresh_scene(bpy.context.scene)
    loaded = {}
    for item_id in result_ids:
        item = next(
            item
            for item in bpy.context.scene.animthumb_items
            if str(item.item_id) == item_id
        )
        cached = package.preview_cache.load_item(item, force=True)
        if cached is None or len(cached.records) < 2:
            raise RuntimeError(f"Preview cache did not load for {item_id}")
        loaded[item_id] = len(cached.records)

    print(
        "ANIMTHUMB_DIRECT_PACKAGE",
        {
            "version": tuple(bpy.app.version),
            "formats": list(expected_formats),
            "loaded_frame_counts": loaded,
        },
    )
finally:
    for item_id in result_ids:
        package.library.remove_item(item_id)
    package.unregister()
