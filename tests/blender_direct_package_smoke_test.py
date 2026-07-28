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
    if int(operator_properties["target_fps"].default) != 22:
        raise RuntimeError("Source-package import FPS default is not 22")
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
    cached_before_refresh = {
        item_id: package.preview_cache._ITEMS[item_id] for item_id in result_ids
    }
    collection_size_before_refresh = len(package.preview_cache._COLLECTION)
    package.library.refresh_scene(bpy.context.scene)
    if any(
        package.preview_cache._ITEMS[item_id] is not cached_before_refresh[item_id]
        for item_id in result_ids
    ):
        raise RuntimeError("No-op library refresh replaced unchanged previews")
    if len(package.preview_cache._COLLECTION) != collection_size_before_refresh:
        raise RuntimeError("No-op library refresh changed the preview collection")

    loaded = {}
    cache_dimensions = {}
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
        image = bpy.data.images.load(
            str(cached.records[0].path),
            check_existing=False,
        )
        try:
            dimensions = tuple(int(value) for value in image.size)
        finally:
            bpy.data.images.remove(image)
        if dimensions != (
            package.constants.MAX_THUMBNAIL_EDGE,
            package.constants.MAX_THUMBNAIL_EDGE,
        ):
            raise RuntimeError(
                f"Preview cache dimensions are {dimensions}, expected "
                f"{package.constants.MAX_THUMBNAIL_EDGE} square"
            )
        cache_dimensions[item_id] = dimensions

    package.preview_cache._reset_statistics()
    frame_bytes = (
        package.constants.MAX_THUMBNAIL_EDGE
        * package.constants.MAX_THUMBNAIL_EDGE
        * package.constants.PREVIEW_DECODED_BYTES_PER_PIXEL
    )
    budget_bytes = frame_bytes * 12
    item_ids = tuple(result_ids)
    for step in range(48):
        now_ms = step * 50
        package.preview_cache.service_visible_items(
            item_ids,
            now_ms,
            fps_limit=60,
            now_monotonic=float(step + 1),
            ram_budget_bytes=budget_bytes,
        )
        for item_id in item_ids:
            package.preview_cache.icon_id(
                item_id,
                now_ms,
                fps_limit=60,
            )
    budget_stats = package.preview_cache.memory_stats()
    if budget_stats["estimated_bytes"] > budget_bytes:
        raise RuntimeError(
            f"Preview RAM budget exceeded: {budget_stats['estimated_bytes']} "
            f"> {budget_bytes}"
        )
    if budget_stats["budget_evictions"] <= 0:
        raise RuntimeError("Preview RAM budget did not evict surplus frames")
    if budget_stats["current_frame_reloads"] != 0:
        raise RuntimeError(
            "Preview RAM budget reloaded frames only after they became current"
        )
    if budget_stats["draw_frame_reloads"] != 0:
        raise RuntimeError("Panel draw had to reload an evicted current frame")

    package.preview_cache.enforce_ram_budget(
        item_ids,
        2_400,
        fps_limit=60,
        ram_budget_bytes=1,
    )
    protected_floor_stats = package.preview_cache.memory_stats()
    if protected_floor_stats["effective_budget_bytes"] <= 1:
        raise RuntimeError("Protected preview working set did not raise the RAM floor")
    if (
        protected_floor_stats["estimated_bytes"]
        > protected_floor_stats["effective_budget_bytes"]
    ):
        raise RuntimeError("Protected working-set floor did not contain loaded frames")

    print(
        "ANIMTHUMB_DIRECT_PACKAGE",
        {
            "version": tuple(bpy.app.version),
            "formats": list(expected_formats),
            "loaded_frame_counts": loaded,
            "cache_dimensions": cache_dimensions,
            "budget_stats": budget_stats,
            "protected_floor_stats": protected_floor_stats,
        },
    )
finally:
    for item_id in result_ids:
        package.library.remove_item(item_id)
    package.unregister()
